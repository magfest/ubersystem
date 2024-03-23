import cherrypy

from uber.config import c
from uber.decorators import ajax, all_renderable, render, credit_card, requires_account
from uber.errors import HTTPRedirect
from uber.models import MarketplaceApplication
from uber.tasks.email import send_email
from uber.utils import check
from uber.payments import TransactionRequest


@all_renderable(public=True)
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
                send_email.delay(
                    c.MARKETPLACE_APP_EMAIL,
                    c.MARKETPLACE_APP_EMAIL,
                    'Marketplace Application Received',
                    render('emails/marketplace/reg_notification.txt',
                           {'app': app}), model=app, encoding=None)
                session.commit()
                raise HTTPRedirect('confirmation?id={}', app.id)

        return {
            'message': message,
            'app': app,
            'attendee': attendee,
            'attendee_id': app.attendee_id or params.get('attendee_id', ''),
            'logged_in_account': session.current_attendee_account(),
            'new_badge': params.get('new_badge', '')
        }

    @requires_account(MarketplaceApplication)
    def edit(self, session, message='', **params):
        app = session.marketplace_application(params, restricted=True,
                                              ignore_csrf=True)
        return_to = params.get('return_to', '/marketplace/edit?id={}'.format(app.id))
        if not params.get('id'):
            message = 'Invalid marketplace application ID. ' \
                      'Please try going back in your browser.'

        if cherrypy.request.method == 'POST':
            message = check(app, prereg=True)
            if not message:
                session.add(app)
                session.commit()  # Make sure we update the DB or the email will be wrong!
                send_email.delay(
                    c.MARKETPLACE_APP_EMAIL,
                    app.email_to_address,
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
            'account': session.get_attendee_account_by_attendee(app.attendee),
            'return_to': 'edit?id={}'.format(app.id),
        }

    def confirmation(self, session, id):
        return {'app': session.marketplace_application(id)}

    @ajax
    @credit_card
    def process_marketplace_payment(self, session, id):
        app = session.marketplace_application(id)

        receipt = session.get_receipt_by_model(app, create_if_none="DEFAULT")

        charge_desc = "{}'s Marketplace Application: {}".format(app.attendee.full_name, receipt.charge_description_list)
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
