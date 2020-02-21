import cherrypy

from uber.config import c
from uber.decorators import ajax, all_renderable, render, credit_card
from uber.errors import HTTPRedirect
from uber.models import MarketplaceApplication
from uber.tasks.email import send_email
from uber.utils import Charge, check


@all_renderable()
class Root:
    def index(self, session, message='', **params):
        attendee = None

        if cherrypy.request.method == 'GET' and params.get('attendee_id', ''):
            try:
                attendee = session.attendee(id=params['attendee_id'])
            except Exception:
                message = \
                    'We could not find you by your confirmation number. ' \
                    'Is the URL correct?'

        if attendee and attendee.group:
            for field in MarketplaceApplication.MATCHING_DEALER_FIELDS:
                params[field] = params[field] if field in params else getattr(attendee.group, field, None)

        app = session.marketplace_application(params, restricted=True,
                                              ignore_csrf=True)

        if not (c.AFTER_MARKETPLACE_REG_START and c.BEFORE_MARKETPLACE_DEADLINE):
            return render('static_views/marketplace_closed.html') if c.AFTER_MARKETPLACE_DEADLINE \
                else render('static_views/marketplace_not_open.html')

        if cherrypy.request.method == 'POST':
            attendee, message = session.attendee_from_marketplace_app(**params)

            message = message or check(attendee) or check(app, prereg=True)
            if not message:
                if c.AFTER_MARKETPLACE_WAITLIST:
                    app.status = c.WAITLISTED
                session.add(attendee)
                app.attendee = attendee

                session.add(app)
                send_email(
                    c.MARKETPLACE_APP_EMAIL,
                    c.MARKETPLACE_APP_EMAIL,
                    'Marketplace Application Received',
                    render('emails/marketplace/reg_notification.txt',
                           {'app': app}), model=app)
                session.commit()
                raise HTTPRedirect('confirmation?id={}', app.id)

        return {
            'message': message,
            'app': app,
            'attendee': attendee,
            'attendee_id': app.attendee_id or params.get('attendee_id', ''),
            'new_badge': params.get('new_badge', '')
        }

    def edit(self, session, message='', **params):
        app = session.marketplace_application(params, restricted=True,
                                              ignore_csrf=True)
        return_to = params['return_to'] \
            if 'return_to' in params else '/marketplace/edit'
        if 'id' not in params:
            message = 'Invalid marketplace application ID. ' \
                      'Please try going back in your browser.'

        if cherrypy.request.method == 'POST':
            message = check(app, prereg=True)
            if not message:
                session.add(app)
                session.commit()  # Make sure we update the DB or the email will be wrong!
                send_email.delay(
                    c.MARKETPLACE_APP_EMAIL,
                    app.email,
                    'Marketplace Application Updated',
                    render('emails/marketplace/appchange_notification.html',
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

    def confirmation(self, session, id):
        return {'app': session.marketplace_application(id)}

    @credit_card
    def process_marketplace_payment(self, session, payment_id, stripeToken):
        charge = Charge.get(payment_id)
        [attendee] = charge.attendees
        attendee = session.merge(attendee)
        apps = attendee.marketplace_applications

        message = charge.charge_cc(session, stripeToken)
        if message:
            raise HTTPRedirect('edit?id={}&message={}',
                               apps[0].id, message)
        else:
            attendee_payment = charge.dollar_amount
            if attendee.marketplace_cost:
                for app in attendee.marketplace_applications:
                    attendee_payment -= app.amount_unpaid
                    app.amount_paid += app.amount_unpaid
            attendee.amount_paid_override += attendee_payment
            if attendee.paid == c.NOT_PAID:
                attendee.paid = c.HAS_PAID
        session.add(attendee)
        send_email.delay(
            c.ADMIN_EMAIL,
            c.MARKETPLACE_APP_EMAIL,
            'Marketplace Payment Received',
            render('emails/marketplace/payment_notification.txt',
                   {'app': app}, encoding=None),
            model=app.to_dict('id'))
        send_email.delay(
            c.MARKETPLACE_APP_EMAIL,
            app.email,
            'Marketplace Payment Received',
            render('emails/marketplace/payment_confirmation.txt',
                   {'app': app}, encoding=None),
            model=app.to_dict('id'))
        raise HTTPRedirect('edit?id={}&message={}',
                           app.id,
                           'Your payment has been accepted!')
