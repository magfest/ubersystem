import cherrypy
from datetime import datetime

from uber.config import c
from uber.custom_tags import email_only
from uber.decorators import ajax, all_renderable, render, credit_card, requires_account
from uber.errors import HTTPRedirect
from uber.models import ArtShowAgentCode, ArtShowApplication
from uber.payments import TransactionRequest
from uber.tasks.email import send_email
from uber.utils import check, RegistrationCode


@all_renderable(public=True)
class Root:
    @requires_account()
    def index(self, session, message='', **params):
        app = session.art_show_application(params, restricted=True,
                                           ignore_csrf=True)
        attendee = None

        if not c.ART_SHOW_OPEN and not c.DEV_BOX:
            return render('static_views/art_show_closed.html') if c.AFTER_ART_SHOW_DEADLINE \
                else render('static_views/art_show_not_open.html')

        if cherrypy.request.method == 'GET' and params.get('attendee_id', ''):
            try:
                attendee = session.attendee(id=params['attendee_id'])
            except Exception:
                message = \
                    'We could not find you by your confirmation number. ' \
                    'Is the URL correct?'

        if cherrypy.request.method == 'POST':
            attendee, message = session.attendee_from_art_show_app(**params)

            if not c.INDEPENDENT_ART_SHOW and attendee and attendee.badge_status == c.NOT_ATTENDING \
                    and app.delivery_method == c.BRINGING_IN:
                message = 'You cannot bring your own art if you are not attending.'

            message = message or check(attendee) or check(app, prereg=True)
            if not message:
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
            'attendee_id': app.attendee_id or params.get('attendee_id', ''),
            'logged_in_account': session.current_attendee_account(),
            'not_attending': params.get('not_attending', ''),
            'new_badge': params.get('new_badge', '')
        }

    @requires_account(ArtShowApplication)
    def edit(self, session, message='', **params):
        return_to = params.get('return_to', '/art_show_applications/edit')

        if not params.get('id'):
            message = 'Invalid art show application ID. ' \
                      'Please try going back in your browser.'

        app = session.art_show_application(params, restricted='art_show_applications' in return_to,
                                           ignore_csrf=True)
        if not app.valid_agent_codes and app.delivery_method == c.AGENT:
            session.add(app.generate_new_agent_code())
            session.commit()

        if cherrypy.request.method == 'POST':
            if c.INDEPENDENT_ART_SHOW:
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
            'receipt': receipt,
            'incomplete_txn': receipt.get_last_incomplete_txn() if receipt else None,
            'homepage_account': session.get_attendee_account_by_attendee(app.attendee),
            'return_to': 'edit?id={}'.format(app.id),
        }

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
            new_txn_requent = TransactionRequest(txn.receipt, app.attendee.email, txn.desc, txn.amount)
            stripe_intent = new_txn_requent.stripe_or_mock_intent()
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
    def save_art_show_piece(self, session, app_id, message='', **params):
        restricted = False if params['return_to'] == '/art_show_admin/pieces' else True
        piece = session.art_show_piece(params, restricted=restricted, bools=['for_sale', 'no_quick_sale'])
        app = session.art_show_application(app_id)

        if restricted:
            if not params.get('name'):
                message += "ERROR: Please enter a name for this piece."
            if not params.get('gallery'):
                message += "<br>" if not params.get('name') else "ERROR: "
                message += "Please select which gallery you will hang this piece in."
            if not params.get('type'):
                message += "<br>" if not params.get('gallery') or not params.get('name') else "ERROR: "
                message += "Please choose whether this piece is a print or an original."
            if message:
                return {'error': message}

        piece.app_id = app.id
        piece.app = app
        message = check(piece)
        if message:
            return {'error': message}

        session.add(piece)
        if not restricted and 'voice_auctioned' not in params:
            piece.voice_auctioned = False
        elif not restricted and 'voice_auctioned' in params and params['voice_auctioned']:
            piece.voice_auctioned = True
        session.commit()

        return {'success': 'Piece "{}" successfully saved'.format(piece.name)}

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
