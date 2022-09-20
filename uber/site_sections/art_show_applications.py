import cherrypy
from six import string_types
from pockets.autolog import log

from uber.config import c
from uber.decorators import ajax, all_renderable, render, credit_card, requires_account
from uber.errors import HTTPRedirect
from uber.models import ArtShowApplication, ModelReceipt
from uber.tasks.email import send_email
from uber.utils import Charge, check


@all_renderable(public=True)
class Root:
    def index(self, session, message='', **params):
        app = session.art_show_application(params, restricted=True,
                                           ignore_csrf=True)
        attendee = None

        if not c.ART_SHOW_OPEN:
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

            if attendee and attendee.badge_status == c.NOT_ATTENDING \
                    and app.delivery_method == c.BRINGING_IN:
                message = 'You cannot bring your own art ' \
                          'if you are not attending.'

            message = message or check(attendee) or check(app, prereg=True)
            if not message:
                if c.AFTER_ART_SHOW_WAITLIST:
                    app.status = c.WAITLISTED
                session.add(attendee)
                app.attendee = attendee

                session.add(app)
                send_email(
                    c.ART_SHOW_EMAIL,
                    c.ART_SHOW_EMAIL,
                    'Art Show Application Received',
                    render('emails/art_show/reg_notification.txt',
                           {'app': app}), model=app)
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

        if cherrypy.request.method == 'POST':
            message = check(app, prereg='art_show_applications' in return_to)
            if not message:
                session.add(app)
                session.commit() # Make sure we update the DB or the email will be wrong!
                send_email.delay(
                    c.ART_SHOW_EMAIL,
                    app.email_to_address,
                    'Art Show Application Updated',
                    render('emails/art_show/appchange_notification.html',
                           {'app': app}, encoding=None),
                    format='html',
                    model=app.to_dict('id'))
                raise HTTPRedirect('..{}?id={}&message={}', return_to, app.id,
                                   'Your application has been updated')
            else:
                session.rollback()
                raise HTTPRedirect('..{}?id={}&message={}', return_to, app.id, message)

        return {
            'message': message,
            'app': app,
            'receipt': session.get_receipt_by_model(app),
            'account': session.get_attendee_account_by_attendee(app.attendee),
            'return_to': 'edit?id={}'.format(app.id),
        }

    @ajax
    def save_art_show_piece(self, session, app_id, message='', **params):
        restricted = False if params['return_to'] == '/art_show_admin/pieces' else True
        piece = session.art_show_piece(params, restricted=restricted, bools=['for_sale', 'no_quick_sale'])
        app = session.art_show_application(app_id)

        if cherrypy.request.method == 'POST':
            piece.app_id = app.id
            piece.app = app
            message = check(piece)
            if not message:
                session.add(piece)
                if not restricted and 'voice_auctioned' not in params:
                    piece.voice_auctioned = False
                elif not restricted and 'voice_auctioned' in params and params['voice_auctioned']:
                    piece.voice_auctioned = True
                session.commit()

        return {'error': message,
                'success': 'Piece "{}" successfully saved'.format(piece.name)}

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

        return {'error': message}

    def confirm_pieces(self, session, id, **params):
        app = session.art_show_application(id)

        if cherrypy.request.method == 'POST':
            send_email.delay(
                c.ART_SHOW_EMAIL,
                app.email_to_address,
                'Art Show Pieces Updated',
                render('emails/art_show/pieces_confirmation.html',
                       {'app': app}, encoding=None), 'html',
                model=app.to_dict('id'))
            raise HTTPRedirect('..{}?id={}&message={}', params['return_to'], app.id,
                               'Confirmation email sent')

    def confirmation(self, session, id):
        return {'app': session.art_show_application(id)}

    def mailing_address(self, session, message='', **params):
        app = session.art_show_application(params)

        if 'copy_address' in params:
            app.address1 = app.attendee.address1
            app.address2 = app.attendee.address2
            app.city = app.attendee.city
            app.region = app.attendee.region
            app.zip_code = app.attendee.zip_code
            app.country = app.attendee.country

        from uber.model_checks import _invalid_zip_code

        if not app.address1:
            message = 'Please enter a street address.'
        if not app.city:
            message = 'Please enter a city.'
        if not app.region and app.country in ['United States', 'Canada']:
            message = 'Please enter a state, province, or region.'
        if not app.country:
            message = 'Please enter a country.'
        if app.country == 'United States':
            if _invalid_zip_code(app.zip_code):
                message = 'Enter a valid zip code'

        if message:
            session.rollback()
        else:
            message = 'Mailing address added.'

        raise HTTPRedirect('edit?id={}&message={}', app.id, message)

    def new_agent(self, session, **params):
        app = session.art_show_application(params['id'])
        promo_code = session.promo_code(code=app.agent_code)
        message = 'Agent code updated'
        page = "edit" if 'admin' not in params else "../art_show_admin/form"

        app.agent_code = app.new_agent_code()
        session.delete(promo_code)
        if app.agent:
            message='Agent removed and code updated'
            send_email.delay(
                c.ART_SHOW_EMAIL,
                [app.agent.email_to_address, app.attendee.email_to_address],
                '{} Art Show Agent Removed'.format(c.EVENT_NAME),
                render('emails/art_show/agent_removed.html',
                       {'app': app}, encoding=None), 'html',
                model=app.to_dict('id'))
            app.agent_id = None

        send_email.delay(
            c.ART_SHOW_EMAIL,
            app.attendee.email_to_address,
            'New Agent Code for the {} Art Show'.format(c.EVENT_NAME),
            render('emails/art_show/agent_code.html',
                   {'app': app}, encoding=None), 'html',
            model=app.to_dict('id'))

        raise HTTPRedirect('{}?id={}&message={}',
                           page, app.id, message)

    def new_agent_app(self, session, id, **params):
        agent = session.attendee(id)

        if not params['agent_code']:
            message = 'Please enter an agent code.'
        else:
            message = check(agent)

        if not message:
            message = 'That application already has an agent.'

            matching_apps = session.lookup_agent_code(params['agent_code'])
            for app in matching_apps:
                if not app.agent:
                    app.agent = agent
                    name = app.artist_name or app.attendee.full_name
                    message = 'You are now an agent for {}.'\
                        .format(name)

        raise HTTPRedirect('../preregistration/confirm?id={}&message={}',
                           id, message)

    @ajax
    @credit_card
    def process_art_show_payment(self, session, id):
        app = session.art_show_application(id)

        receipt = session.get_receipt_by_model(app)

        if not receipt:
            receipt, receipt_items = Charge.create_model_receipt(app)
            session.add(receipt)
            for item in receipt_items:
                session.add(item)
            session.commit()
        
        charge_desc = "{}'s Art Show Application: {}".format(app.attendee.full_name, receipt.charge_description_list)
        charge = Charge(app, amount=receipt.current_amount_owed, description=charge_desc)
        
        stripe_intent = charge.create_stripe_intent()

        if isinstance(stripe_intent, string_types):
            return {'error': stripe_intent}
        
        receipt_txn = Charge.create_receipt_transaction(receipt, charge_desc, stripe_intent.id)
        session.add(receipt_txn)
        session.commit()

        send_email.delay(
            c.ADMIN_EMAIL,
            c.ART_SHOW_EMAIL,
            'Art Show Payment Received',
            render('emails/art_show/payment_notification.txt',
                {'app': app}, encoding=None),
            model=app.to_dict('id'))
        send_email.delay(
            c.ART_SHOW_EMAIL,
            app.email_to_address,
            'Art Show Payment Received',
            render('emails/art_show/payment_confirmation.txt',
                {'app': app}, encoding=None),
            model=app.to_dict('id'))
    
        return {'stripe_intent': stripe_intent,
                'success_url': 'edit?id={}&message={}'.format(app.id,
                                                                'Your payment has been accepted'),
                'cancel_url': '../preregistration/cancel_payment'}
