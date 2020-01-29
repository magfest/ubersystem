import cherrypy

from uber.config import c
from uber.decorators import ajax, all_renderable, render, credit_card
from uber.errors import HTTPRedirect
from uber.tasks.email import send_email
from uber.utils import Charge, check


@all_renderable()
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

            # We do an extra check here to handle new attendees
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
            'not_attending': params.get('not_attending', ''),
            'new_badge': params.get('new_badge', '')
        }

    def edit(self, session, message='', **params):
        app = session.art_show_application(params, restricted=True,
                                           ignore_csrf=True)
        return_to = params['return_to'] \
            if 'return_to' in params else '/art_show_applications/edit'
        if 'id' not in params:
            message = 'Invalid art show application ID. ' \
                      'Please try going back in your browser.'

        if cherrypy.request.method == 'POST':
            message = check(app, prereg=True)
            if not message:
                session.add(app)
                session.commit() # Make sure we update the DB or the email will be wrong!
                send_email.delay(
                    c.ART_SHOW_EMAIL,
                    app.email,
                    'Art Show Application Updated',
                    render('emails/art_show/appchange_notification.html',
                           {'app': app}, encoding=None), 'html',
                    model=app.to_dict('id'))
                raise HTTPRedirect('..{}?id={}&message={}', return_to, app.id,
                                   'Your application has been updated')
            else:
                session.rollback()

        return {
            'message': message,
            'app': app,
            'return_to': 'edit',
            'charge': Charge(app.attendee)
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
                app.email,
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
                [app.agent.email, app.attendee.email],
                '{} Art Show Agent Removed'.format(c.EVENT_NAME),
                render('emails/art_show/agent_removed.html',
                       {'app': app}, encoding=None), 'html',
                model=app.to_dict('id'))
            app.agent_id = None

        send_email.delay(
            c.ART_SHOW_EMAIL,
            app.attendee.email,
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

    @credit_card
    def process_art_show_payment(self, session, payment_id, stripeToken):
        charge = Charge.get(payment_id)
        [attendee] = charge.attendees
        attendee = session.merge(attendee)
        apps = attendee.art_show_applications
        for app in apps:
            message = charge.charge_cc(session, stripeToken)
            if message:
                raise HTTPRedirect('edit?id={}&message={}',
                                   app.id, message)
            else:
                attendee.amount_paid_override += charge.dollar_amount
                app.status = c.PAID
                if attendee.paid == c.NOT_PAID:
                    attendee.paid = c.HAS_PAID
            session.add(attendee)
            send_email.delay(
                c.ADMIN_EMAIL,
                c.ART_SHOW_EMAIL,
                'Art Show Payment Received',
                render('emails/art_show/payment_notification.txt',
                       {'app': app}, encoding=None),
                model=app.to_dict('id'))
            send_email.delay(
                c.ART_SHOW_EMAIL,
                app.email,
                'Art Show Payment Received',
                render('emails/art_show/payment_confirmation.txt',
                       {'app': app}, encoding=None),
                model=app.to_dict('id'))
            raise HTTPRedirect('edit?id={}&message={}',
                               app.id,
                               'Your payment has been accepted!')
