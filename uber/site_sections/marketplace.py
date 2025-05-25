import cherrypy

from datetime import datetime
from pockets.autolog import log

from uber.config import c
from uber.custom_tags import email_only
from uber.decorators import ajax, all_renderable, render, credit_card, requires_account, public
from uber.errors import HTTPRedirect
from uber.forms import load_forms
from uber.models import Attendee, ArtistMarketplaceApplication
from uber.tasks.email import send_email
from uber.utils import check, validate_model
from uber.payments import TransactionRequest, ReceiptManager


@all_renderable(public=True)
class Root:
    @requires_account(Attendee)
    def apply(self, session, message='', attendee_id=None, **params):
        if attendee_id:
            attendee = session.attendee(attendee_id)
        else:
            attendee = None
            account = session.current_attendee_account()
            can_apply = [a for a in account.valid_attendees if a.has_badge or a.badge_status == c.UNAPPROVED_DEALER_STATUS]
            if len(can_apply) == 1:
                attendee = can_apply[0]
            else:
                raise HTTPRedirect('../preregistration/homepage?message={}',
                                   f"Please select a badge below to apply to the artist marketplace.")

        if not attendee.has_badge and not attendee.badge_status == c.UNAPPROVED_DEALER_STATUS:
            raise HTTPRedirect('../preregistration/homepage?message={}',
                               f"You cannot apply to the artist marketplace with a {attendee.badge_status_label} badge.")
        if attendee.marketplace_application:
            raise HTTPRedirect('edit?id={}&message={}',
                               attendee.marketplace_application.id,
                               "You already have a marketplace application, which you can view below.")

        if attendee.is_group_leader and attendee.is_dealer:
            for field in ArtistMarketplaceApplication.MATCHING_DEALER_FIELDS:
                group_data = getattr(attendee.group, field)
                if field not in params and group_data:
                    params[field] = group_data

        app = ArtistMarketplaceApplication(attendee_id=attendee.id)
        forms_list = ["ArtistMarketplaceForm"]
        forms = load_forms(params, app, forms_list)

        if cherrypy.request.method == 'POST':
            for form in forms.values():
                form.populate_obj(app)
            if c.AFTER_MARKETPLACE_WAITLIST:
                app.status = c.WAITLISTED
            if params.get('copy_email'):
                app.email_address = attendee.email
            session.add(app)

            raise HTTPRedirect('confirmation?id={}', app.id)

        return {
            'message': message,
            'app': app,
            'forms': forms,
            'attendee': attendee,
            'attendee_id': attendee_id,
            'homepage_account': session.current_attendee_account(),
        }

    @requires_account(ArtistMarketplaceApplication)
    def edit(self, session, message='', id=None, **params):
        if not id:
            return {
                'message': 'Invalid marketplace application ID. Please try going back in your browser.',
                'app': session.artist_marketplace_application(params),
                'account': session.current_attendee_account(),
            }
        else:
            app = session.artist_marketplace_application(id)
            forms_list = ["ArtistMarketplaceForm"]
            forms = load_forms(params, app, forms_list)

        if cherrypy.request.method == 'POST':
            old_app = {}
            old_app['name'] = app.name
            old_app['display_name'] = app.display_name

            for form in forms.values():
                form.populate_obj(app)
            session.add(app)
            session.commit()
            session.refresh(app)

            if app.status == c.ACCEPTED:
                send_email.delay(
                    c.ARTIST_MARKETPLACE_EMAIL,
                    c.ARTIST_MARKETPLACE_EMAIL,
                    'Marketplace Application Updated',
                    render('emails/marketplace/appchange_notification.html',
                            {'app': app, 'old_app': old_app}, encoding=None), 'html',
                    model=app.to_dict('id'))
            raise HTTPRedirect('edit?id={}&message={}', app.id,
                                'Your application has successfully been updated.')

        return {
            'message': message,
            'app': app,
            'forms': forms,
            'homepage_account': session.current_attendee_account(),
        }
    
    @ajax
    @requires_account(ArtistMarketplaceApplication)
    def validate_marketplace_app(self, session, form_list=[], **params):
        if params.get('id') in [None, '', 'None']:
            app = ArtistMarketplaceApplication()
        else:
            app = session.artist_marketplace_application(params.get('id'))

        if not form_list:
            form_list = ["ArtistMarketplaceForm"]
        elif isinstance(form_list, str):
            form_list = [form_list]
        forms = load_forms(params, app, form_list)

        all_errors = validate_model(forms, app, ArtistMarketplaceApplication(**app.to_dict()), is_admin=False)
        if all_errors:
            return {"error": all_errors}

        return {"success": True}

    def confirmation(self, session, id):
        return {
            'app': session.artist_marketplace_application(id),
            'homepage_account': session.current_attendee_account(),
        }

    def cancel(self, session, id):
        if c.AFTER_MARKETPLACE_CANCEL_DEADLINE:
            raise HTTPRedirect('edit?id={}&message={}', id,
                               f"Please contact us at {email_only(c.ARTIST_MARKETPLACE_EMAIL)} "
                               "to cancel your application.")
        app = session.artist_marketplace_application(id)
        if app.amount_paid:
            credit_item = ReceiptManager().create_receipt_item(session.get_receipt_by_model(app.attendee),
                                                               c.ARTIST_ALLEY_RECEIPT_ITEM, c.CANCEL_ITEM,
                                                               "Cancelling Artist Marketplace Application",
                                                               app.amount_paid * -1)
            credit_item.fk_id = id
            credit_item.fk_model = 'ArtistMarketplaceApplication'
            session.add(credit_item)
            running_total = app.amount_paid
            for item in app.receipt_items:
                if item.closed and item.receipt_txn and item.receipt_txn.amount_left:
                    if item.receipt_txn.amount_left > running_total:
                        refund_amount = running_total
                    else:
                        refund_amount = item.receipt_txn.amount_left
                    running_total = running_total - refund_amount
                    refund = TransactionRequest(item.receipt, amount=refund_amount, who='non-admin')
                    error = refund.refund_or_cancel(item.receipt_txn, c.ARTIST_ALLEY_RECEIPT_ITEM)
                    if error:
                        log.error(f"Tried to cancel marketplace app {app.id} but ran into an error: {error}")
                        raise HTTPRedirect('edit?id={}&message={}', id,
                                           f"There was an issue processing your refund. "
                                           "Please contact us at {email_only(c.ARTIST_MARKETPLACE_EMAIL)}.")
                    session.add_all(refund.get_receipt_items_to_add())
            session.commit()
            session.check_receipt_closed(session.get_receipt_by_model(app.attendee))

        if app.status == c.ACCEPTED:
            send_email.delay(
                    c.ARTIST_MARKETPLACE_EMAIL,
                    c.ARTIST_MARKETPLACE_EMAIL,
                    'Marketplace Application Cancelled',
                    render('emails/marketplace/cancelled.txt',
                            {'app': app}, encoding=None),
                    model=app.to_dict('id'))
        app.status = c.CANCELLED

        if c.ATTENDEE_ACCOUNTS_ENABLED:
            raise HTTPRedirect('../preregistration/homepage?message={}',
                               "Application cancelled.")
        else:
            raise HTTPRedirect('../preregistration/confirm?id={}&message={}', app.attendee.id,
                               "Application cancelled.")

    @ajax
    @credit_card
    @requires_account(ArtistMarketplaceApplication)
    def process_marketplace_payment(self, session, id):
        app = session.artist_marketplace_application(id)

        receipt = session.get_receipt_by_model(app.attendee, create_if_none="DEFAULT")
        if not app.receipt_items or app.was_refunded:
            receipt_item = ReceiptManager().create_receipt_item(receipt,
                                                                c.ARTIST_ALLEY_RECEIPT_ITEM,
                                                                c.MARKETPLACE,
                                                                "Artist Marketplace Application",
                                                                app.amount_unpaid,
                                                                purchaser_id=app.attendee.id)
            receipt_item.fk_id = app.id
            receipt_item.fk_model = "ArtistMarketplaceApplication"
            session.add(receipt_item)
            session.commit()
            session.refresh(receipt)
        
        charge = TransactionRequest(receipt, app.email_address,
                                    "Artist Marketplace Application Payment", amount=app.amount_unpaid)
        incomplete_txn = receipt.get_last_incomplete_txn()

        if incomplete_txn and incomplete_txn.desc == "Artist Marketplace Application Payment":
            if c.AUTHORIZENET_LOGIN_ID:
                stripe_intent = charge.stripe_or_mock_intent()
                incomplete_txn.intent_id = stripe_intent.id
            else:
                error = incomplete_txn.check_stripe_id()
                if error:
                    incomplete_txn.cancelled = datetime.now()
                    session.add(incomplete_txn)
                    message = charge.prepare_payment(department=c.ARTIST_ALLEY_RECEIPT_ITEM)
                    if message:
                        return {'error': message}
                    stripe_intent = charge.intent
                else:
                    stripe_intent = stripe_intent.get_stripe_intent()
                    if stripe_intent.status == "succeeded":
                        return {'error': "This payment has already been finalized!"}
        else:
            message = charge.prepare_payment(department=c.ARTIST_ALLEY_RECEIPT_ITEM)

            if message:
                return {'error': message}
            
            stripe_intent = charge.intent

        if stripe_intent == charge.intent:
            session.add_all(charge.get_receipt_items_to_add())

        session.commit()

        return {'stripe_intent': stripe_intent,
                'success_url': 'edit?id={}&message={}'.format(app.id,
                                                              'Your payment has been accepted.'),
                'cancel_url': '../preregistration/cancel_payment'}
