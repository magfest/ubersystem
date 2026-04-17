import os
import stripe
import logging
import cherrypy
from cherrypy.lib.static import serve_file
from sqlalchemy.orm.exc import NoResultFound
import base64

from uber.config import c
from uber.decorators import ajax, all_renderable, not_site_mappable
from uber.errors import HTTPRedirect
from uber.models import GuestMerch, GuestDetailedTravelPlan, GuestTravelPlans, GuestPanel
from uber.model_checks import mivs_show_info_required_fields
from uber.utils import check, filename_extension
from uber.tasks.email import send_email
from uber.files import FileService
from uber.payments import ReceiptManager


log = logging.getLogger(__name__)


@all_renderable(public=True)
class Root:
    @not_site_mappable
    def download_file(self, session, id, filename='', preview=False):
        file_handler = FileService.from_db_id(session, id)
        if preview:
            return file_handler.preview(filename=filename)
        else:
            return file_handler.serve_file(filename=filename)

    @not_site_mappable
    def oidc_handler(self, code=None, error=None, post_login_url='', **kwargs):
        if error:
            raise HTTPRedirect("../landing/index?message={}", f"Login failed: {error}")

        cherrypy.tools.oidc.error = ''
        redirect_uri = f"{c.OIDC_REDIRECT_URL}?post_login_url={post_login_url}" if post_login_url else c.OIDC_REDIRECT_URL
        cherrypy.tools.oidc.handle_login(code, redirect_uri=redirect_uri)

        if cherrypy.tools.oidc.error:
            raise HTTPRedirect('../landing/index?message={}', cherrypy.tools.oidc.error)
        
        post_login_url = base64.urlsafe_b64decode(post_login_url.encode()).decode()

        if getattr(cherrypy.request, 'admin_account', None) and c.AT_THE_CON:
            raise HTTPRedirect(post_login_url or '../accounts/homepage')
        elif getattr(cherrypy.request, 'attendee_account', None):
            raise HTTPRedirect(post_login_url or '../preregistration/homepage')
        raise HTTPRedirect('../landing/index?message={}', f'Login failed.')
    
    @not_site_mappable
    def stripe_webhook_handler(self):
        if not cherrypy.request or not cherrypy.request.body:
            cherrypy.response.status = 400
            return "Request required"
        sig_header = cherrypy.request.headers.get('Stripe-Signature', '')
        payload = cherrypy.request.body.read()
        event = None

        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, c.STRIPE_ENDPOINT_SECRET
            )
        except ValueError:
            cherrypy.response.status = 400
            return "Invalid payload: " + payload
        except stripe.error.SignatureVerificationError:
            cherrypy.response.status = 400
            return "Invalid signature: " + sig_header

        if not event:
            cherrypy.response.status = 400
            return "No event"

        if event and event['type'] == 'payment_intent.succeeded':
            payment_intent = event['data']['object']
            matching_txns = ReceiptManager.mark_paid_from_stripe_intent(payment_intent)
            if not matching_txns:
                cherrypy.response.status = 400
                return "No matching Stripe transactions"
            cherrypy.response.status = 200
            return "Payments marked complete for payment intent ID " + payment_intent['id']