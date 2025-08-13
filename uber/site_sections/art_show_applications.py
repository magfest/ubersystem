import cherrypy
from datetime import datetime

from uber.config import c
from uber.custom_tags import email_only, readable_join
from uber.decorators import ajax, all_renderable, render, credit_card, requires_account
from uber.errors import HTTPRedirect
from uber.forms import load_forms
from uber.models import ArtShowAgentCode, ArtShowApplication, Attendee, ArtShowBidder, ArtShowPiece
from uber.payments import TransactionRequest
from uber.tasks.email import send_email
from uber.utils import check, validate_model


@all_renderable(public=True)
class Root:
    @requires_account()
    def index(self, session, message='', **params):
        if not c.ART_SHOW_OPEN and not c.DEV_BOX:
            return render('static_views/art_show_closed.html') if c.AFTER_ART_SHOW_DEADLINE \
                else render('static_views/art_show_not_open.html')

        app = ArtShowApplication()
        attendee = Attendee()

        if cherrypy.request.method == 'GET' and params.get('attendee_id', ''):
            try:
                attendee = session.attendee(id=params['attendee_id'])
            except Exception:
                message = \
                    'We could not find you by your confirmation number. Is the URL correct?'

        app_forms = load_forms(params, app, ["ArtShowInfo"])
        attendee_forms = load_forms(params, attendee, ["ArtistAttendeeInfo"])

        if cherrypy.request.method == 'POST':
            attendee, message = session.attendee_from_art_show_app(**params)

            if not message:
                for form in app_forms.values():
                    form.populate_obj(app)
                if attendee.is_new:
                    for form in attendee_forms.values():
                        form.populate_obj(attendee)

                if c.ART_SHOW_WAITLIST and c.AFTER_ART_SHOW_WAITLIST:
                    app.status = c.WAITLISTED
                session.add(attendee)
                app.attendee = attendee

                session.add(app)
                send_email.delay(
                    c.ART_SHOW_EMAIL,
                    c.ART_SHOW_NOTIFICATIONS_EMAIL,
                    'Art Show Application Received',
                    render('emails/art_show/reg_notification.txt',
                            {'app': app}, encoding=None), model=app.to_dict('id'))
                session.commit()
                raise HTTPRedirect('confirmation?id={}', app.id)

        return {
            'message': message,
            'app': app,
            'attendee': attendee,
            'app_forms': app_forms,
            'attendee_forms': attendee_forms,
            'attendee_id': app.attendee_id or params.get('attendee_id', ''),
            'logged_in_account': session.current_attendee_account(),
            'not_attending': params.get('not_attending', ''),
            'new_badge': params.get('new_badge', '')
        }
    
    @ajax
    def validate_app(self, session, form_list=[], **params):
        all_errors = {}

        if params.get('id') in [None, '', 'None']:
            app = ArtShowApplication()
            attendee, message = session.attendee_from_art_show_app(**params)
            if message:
                attendee = Attendee(placeholder=True)
                all_errors[''] = [message]
        else:
            app = session.art_show_application(params.get('id'))
            attendee = app.attendee

        if not form_list:
            form_list = ['ArtShowInfo']
        elif isinstance(form_list, str):
            form_list = [form_list]

        if attendee.is_new and not c.INDEPENDENT_ART_SHOW and not params.get('attendee_id', '') and 'new_badge' not in params:
            all_errors['attendee_id'] = [f"Please enter your confirmation number or confirm that you are not registered for {c.EVENT_NAME}"]
        elif attendee.is_new or c.INDEPENDENT_ART_SHOW:
            attendee_forms = load_forms(params, attendee, ['ArtistAttendeeInfo'])
            attendee_errors = validate_model(attendee_forms, attendee)
            if attendee_errors:
                all_errors.update(attendee_errors)

        forms = load_forms(params, app, form_list)
        app_errors = validate_model(forms, app)

        if app_errors:
            all_errors.update(app_errors)
        
        if all_errors:
            return {"error": all_errors}

        return {"success": True}

    @requires_account(ArtShowApplication)
    def edit(self, session, message='', **params):
        return_to = params.get('return_to', '/art_show_applications/edit')

        if not params.get('id'):
            message = 'Invalid art show application ID. Please try going back in your browser.'

        app = session.art_show_application(params.get('id'))
        if not app.valid_agent_codes and app.delivery_method == c.AGENT:
            session.add(app.generate_new_agent_code())
            session.commit()

        forms = load_forms(params, app, ["ArtShowInfo"], read_only=not app.is_new and not app.editable)
        forms.update(load_forms(params, app, ["ArtistMailingInfo"]))

        piece_forms = {}
        piece_forms['new'] = load_forms({}, ArtShowPiece(), ['ArtShowPieceInfo'],
                                        field_prefix='new', read_only=app.checked_in)

        for piece in app.art_show_pieces:
            piece_forms[piece.id] = load_forms({}, piece, ['ArtShowPieceInfo'],
                                               field_prefix=piece.id, read_only=app.checked_in)

        if cherrypy.request.method == 'POST':
            if c.INDEPENDENT_ART_SHOW:
                app.special_requests = app.orig_value_of('special_requests')
                attendee_params = {}
                for key in [param for param in params if param.startswith('attendee_')]:
                    val = params.pop(key)
                    attendee_params[key.replace('attendee_', '')] = val

                attendee = session.attendee(attendee_params, restricted='art_show_applications' in return_to,
                                            ignore_csrf=True)
                message = check(attendee, prereg='art_show_applications' in return_to)
                if not message:
                    session.add(attendee)
            if not message:
                message = check(app, prereg='art_show_applications' in return_to)
            if not message:
                for form in forms.values():
                    form.populate_obj(app)
                session.add(app)
                session.commit()  # Make sure we update the DB or the email will be wrong!
                send_email.delay(
                    c.ART_SHOW_EMAIL,
                    app.email_to_address,
                    'Art Show Application Updated',
                    render('emails/art_show/appchange_notification.html',
                           {'app': app}, encoding=None),
                    bcc=c.ART_SHOW_BCC_EMAIL,
                    format='html',
                    model=app.to_dict('id'))
                raise HTTPRedirect('..{}?id={}&message={}', return_to, app.id,
                                   'Your application has been updated')
            else:
                session.rollback()
                raise HTTPRedirect('..{}?id={}&message={}', return_to, app.id, message)

        receipt = session.refresh_receipt_and_model(app)

        return {
            'message': message,
            'app': app,
            'forms': forms,
            'piece_forms': piece_forms,
            'receipt': receipt,
            'incomplete_txn': receipt.get_last_incomplete_txn() if receipt else None,
            'homepage_account': session.get_attendee_account_by_attendee(app.attendee),
            'return_to': 'edit?id={}'.format(app.id),
        }
    
    @ajax
    def validate_art_show_piece(self, session, form_list=[], **params):
        if params.get('id') in [None, '', 'None']:
            piece = ArtShowPiece()
            piece.app_id = params.get('app_id')
        else:
            piece = session.art_show_piece(params.get('id'))

        if not form_list:
            form_list = ['ArtShowPieceInfo']
        elif isinstance(form_list, str):
            form_list = [form_list]

        forms = load_forms(params, piece, form_list, field_prefix='new' if piece.is_new else piece.id)
        all_errors = validate_model(forms, piece)

        if all_errors:
            return {"error": all_errors}

        return {"success": True}

    @ajax
    @credit_card
    @requires_account(ArtShowApplication)
    def finish_pending_payment(self, session, id, txn_id, **params):
        app = session.art_show_application(id)
        txn = session.receipt_transaction(txn_id)

        error = txn.check_stripe_id()
        if error:
            return {'error': "Something went wrong with this payment. Please refresh the page and try again."}

        if c.AUTHORIZENET_LOGIN_ID:
            # Authorize.net doesn't actually have a concept of pending transactions,
            # so there's no transaction to resume. Create a new one.
            new_txn_request = TransactionRequest(txn.receipt, app.attendee.email, txn.desc, txn.amount)
            stripe_intent = new_txn_request.generate_payment_intent()
            txn.intent_id = stripe_intent.id
            session.commit()
        else:
            stripe_intent = txn.get_stripe_intent()

        if not stripe_intent:
            return {'error': "Something went wrong. Please contact us at {}.".format(email_only(c.REGDESK_EMAIL))}

        if not c.AUTHORIZENET_LOGIN_ID and stripe_intent.status == "succeeded":
            return {'error': "This payment has already been finalized!"}

        return {'stripe_intent': stripe_intent,
                'success_url': 'edit?id={}&message={}'.format(
                    app.id,
                    'Your payment has been accepted!'),
                'cancel_url': 'cancel_payment'}

    @ajax
    def save_art_show_piece(self, session, app_id, **params):
        if params.get('id') in [None, '', 'None']:
            piece = ArtShowPiece()
        else:
            piece = session.art_show_piece(params.get('id'))

        app = session.art_show_application(app_id)

        forms = load_forms(params, piece, ['ArtShowPieceInfo'], field_prefix='new' if piece.is_new else piece.id)
        for form in forms.values():
            form.populate_obj(piece)

        piece.app = app
        success_verb = "added" if piece.is_new else "updated"
        session.add(piece)

        session.commit()

        return {'success': f'Piece "{piece.name}" {success_verb}.',
                'hash': 'piece-modal-new' if params.get('save_add_piece', '') else ''}

    @ajax
    def remove_art_show_piece(self, session, id, **params):
        piece = session.art_show_piece(id)

        message = ''

        if cherrypy.request.method == 'POST':
            if not piece:
                message = 'Piece not found'
            else:
                session.delete(piece)
                session.commit()
                return {}

        return {'error': message}

    def confirm_pieces(self, session, id, **params):
        app = session.art_show_application(id)

        if cherrypy.request.method == 'POST':
            send_email.delay(
                c.ART_SHOW_EMAIL,
                [app.email_to_address, c.ART_SHOW_NOTIFICATIONS_EMAIL],
                f'[{app.artist_codes}] {c.EVENT_NAME} Art Show: Pieces Updated',
                render('emails/art_show/pieces_confirmation.html',
                       {'app': app}, encoding=None), 'html',
                model=app.to_dict('id'))
            raise HTTPRedirect('..{}?id={}&message={}', params['return_to'], app.id,
                               'Confirmation email sent!')

    def confirmation(self, session, id):
        return {
            'app': session.art_show_application(id),
            'logged_in_account': session.current_attendee_account(),
        }

    def mailing_address(self, session, message='', **params):
        app = session.art_show_application(params)

        if 'copy_address' in params:
            app.address1 = app.attendee.address1
            app.address2 = app.attendee.address2
            app.city = app.attendee.city
            app.region = app.attendee.region
            app.zip_code = app.attendee.zip_code
            app.country = app.attendee.country

        from uber.model_checks import invalid_zip_code

        if not app.address1:
            message = 'Please enter a street address.'
        if not app.city:
            message = 'Please enter a city.'
        if not app.region and app.country in ['United States', 'Canada']:
            message = 'Please enter a state, province, or region.'
        if not app.country:
            message = 'Please enter a country.'
        if app.country == 'United States':
            if invalid_zip_code(app.zip_code):
                message = 'Enter a valid zip code'

        if message:
            session.rollback()
        else:
            message = 'Mailing address added.'

        raise HTTPRedirect('edit?id={}&message={}', app.id, message)

    def cancel_agent_code(self, session, id, **params):
        old_code = session.art_show_agent_code(id)
        app = old_code.app
        message = 'Agent code cancelled.'
        page = "edit" if 'admin' not in params else "../art_show_admin/form"

        old_code.cancelled = datetime.now()

        if old_code.attendee:
            message = 'Agent removed.'
            send_email.delay(
                c.ART_SHOW_EMAIL,
                [old_code.attendee.email_to_address, app.attendee.email_to_address],
                '{} Art Show Agent Removed'.format(c.EVENT_NAME),
                render('emails/art_show/agent_removed.html',
                       {'app': app, 'agent': old_code.attendee}, encoding=None), 'html',
                bcc=c.ART_SHOW_BCC_EMAIL,
                model=app.to_dict('id'))

        session.commit()
        session.refresh(app)
        if not app.valid_agent_codes:
            new_code = app.generate_new_agent_code()
            session.add(new_code)
            if page == 'edit':
                message += f' Your new agent code is {new_code.code}.'
            else:
                send_email.delay(
                    c.ART_SHOW_EMAIL,
                    app.attendee.email_to_address,
                    'New Agent Code for the {} Art Show'.format(c.EVENT_NAME),
                    render('emails/art_show/agent_code.html',
                        {'app': app, 'agent_code': new_code}, encoding=None), 'html',
                    bcc=c.ART_SHOW_BCC_EMAIL,
                    model=app.to_dict('id'))

        raise HTTPRedirect('{}?id={}&message={}', page, app.id, message)
    
    def add_agent_code(self, session, id, **pararms):
        app = session.art_show_application(id)
        new_code = app.generate_new_agent_code()
        session.add(new_code)

        raise HTTPRedirect('edit?message=', f'New agent code "{new_code.code}" added!')

    def new_agent_app(self, session, id, **params):
        agent = session.attendee(id)

        if not params['agent_code']:
            message = 'Please enter an agent code.'
        else:
            message = check(agent)

        if not message:
            agent_code = session.lookup_registration_code(params['agent_code'], ArtShowAgentCode)
            if not agent_code:
                message = 'We could not find that code!'
            elif agent_code.cancelled:
                message = 'That code can no longer be used.'
            
        if not message:
            agent_code.attendee = agent
            message = f'You are now an agent for {agent_code.app.display_name}.'                   

        raise HTTPRedirect('../preregistration/confirm?id={}&message={}', id, message)

    @ajax
    @credit_card
    def process_art_show_payment(self, session, id):
        app = session.art_show_application(id)

        receipt = session.get_receipt_by_model(app, create_if_none="DEFAULT")

        charge_desc = "{}'s Art Show Application: {}".format(app.attendee.full_name, receipt.charge_description_list)
        charge = TransactionRequest(receipt, app.attendee.email, charge_desc)

        message = charge.prepare_payment()

        if message:
            return {'error': message}

        session.add_all(charge.get_receipt_items_to_add())
        session.commit()

        return {'stripe_intent': charge.intent,
                'success_url': 'edit?id={}&message={}'.format(app.id,
                                                              'Your payment has been accepted'),
                'cancel_url': '../preregistration/cancel_payment'}

    def bidder_signup(self, session, message='', **params):
        # TODO: Make this work with the new form system. Sorry, future-me
        if c.INDEPENDENT_ART_SHOW:
            attendee = Attendee(
                placeholder=True,
                badge_status=c.NOT_ATTENDING,
                )
        else:
            raise HTTPRedirect('index')
        
        if cherrypy.request.method == 'POST':
            missing_fields = []
            
            for field_name in params.copy().keys():
                if params.get(field_name, None):
                    if hasattr(attendee, field_name) and (not hasattr(ArtShowBidder(), field_name) or field_name == 'email'):
                        setattr(attendee, field_name, params.pop(field_name))
                elif field_name in ArtShowBidder.required_fields.keys():
                    if field_name not in ['bidder_num', 'badge_printed_name']: # Admin only
                        missing_fields.append(ArtShowBidder.required_fields[field_name])
            
            dupe_badge_num = session.query(Attendee).filter(Attendee.id != attendee.id,
                                                            Attendee.badge_num != None,
                                                            Attendee.badge_num == attendee.badge_num).first()

            dupe_attendee = session.query(Attendee).filter(Attendee.id != attendee.id,
                                                           Attendee.first_name == attendee.first_name,
                                                           Attendee.last_name == attendee.last_name,
                                                           Attendee.email == attendee.email).first()
            if dupe_badge_num:
                message = 'We already have information for this badge number. Please check the badge number you entered \
                    or check in with a staff member at a "Bidder Sign-Up" table to complete the signup process.'
            elif dupe_attendee:
                message = 'We already have your information. \
                    Please check in with a staff member at a "Bidder Sign-Up" table to complete the signup process.'
            elif missing_fields:
                message = "Please fill out the following fields: " + readable_join(missing_fields) + "."
            elif 'phone_type' not in params:
                message = "You must select whether your phone number is a mobile number or a landline."
            elif 'pickup_time_acknowledged' not in params:
                message = "You must acknowledge that you understand our art pickup policies."

            bidder = ArtShowBidder(phone_type=0)
            attendee.art_show_bidder = bidder

            bidder.apply(params, restricted=True)

            if not message:
                session.add(attendee)
                raise HTTPRedirect('bidder_signup?signup_complete=True')

        return {
            'message': message,
            'attendee': attendee,
            'signup_complete': params.get('signup_complete', False),
            'logged_in_account': session.current_attendee_account(),
        }