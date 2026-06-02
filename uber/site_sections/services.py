import os
import stripe
import logging
import cherrypy
import pytz
from datetime import datetime
from cherrypy.lib.static import serve_file
from sqlalchemy.orm.exc import NoResultFound
from urllib.parse import urlparse, parse_qsl
import base64

from uber.config import c
from uber.decorators import ajax, all_renderable, not_site_mappable
from uber.errors import HTTPRedirect
from uber.models import AdminAccount, AttendeeAccount
from uber.model_checks import mivs_show_info_required_fields
from uber.utils import check, filename_extension
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
    def oidc_handler(self, session, code=None, error=None, post_login_url='', **kwargs):
        if error:
            raise HTTPRedirect("../landing/index?message={}", f"Login failed: {error}")

        orig_redirect_uri = f"{c.OIDC_REDIRECT_URL}?post_login_url={post_login_url}" if post_login_url else c.OIDC_REDIRECT_URL
        post_login_url = base64.urlsafe_b64decode(post_login_url.encode()).decode()
        params = dict(parse_qsl(urlparse(post_login_url).query))
        error = cherrypy.tools.oidc.handle_login(code, redirect_uri=orig_redirect_uri,
                                                 account_claim_token=params.get('sso_claim_token'))
        
        if error:
            raise HTTPRedirect('../landing/index?message={}', error)
        
        redirect_url = getattr(cherrypy.request, 'redirect_url', post_login_url)

        admin_account_id = getattr(cherrypy.request, 'admin_account', None)
        attendee_account_id = getattr(cherrypy.request, 'attendee_account', None)
        now = datetime.now(pytz.UTC)
        if admin_account_id:
            login_account = session.get(AdminAccount, admin_account_id)
            login_account.last_signed_in = now
            session.add(login_account)
        if attendee_account_id:
            login_account = session.get(AttendeeAccount, attendee_account_id)
            login_account.last_signed_in = now
            session.add(login_account)
        
        if getattr(cherrypy.request, 'admin_account', None) and c.AT_THE_CON:
            raise HTTPRedirect(redirect_url or '../accounts/homepage')
        elif getattr(cherrypy.request, 'attendee_account', None):
            raise HTTPRedirect(redirect_url or '../preregistration/homepage')
    
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