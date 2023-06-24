import json
from datetime import datetime, timedelta
from functools import wraps
from uber.models import PasswordReset
from uber.models.marketplace import MarketplaceApplication
from uber.models.art_show import ArtShowApplication

import bcrypt
import cherrypy
from collections import defaultdict
from pockets import listify
from pockets.autolog import log
from six import string_types
from sqlalchemy import func
from sqlalchemy.orm.exc import NoResultFound
from onelogin.saml2.auth import OneLogin_Saml2_Auth
from onelogin.saml2.settings import OneLogin_Saml2_Settings
from onelogin.saml2.utils import OneLogin_Saml2_Utils
from urllib.parse import urlparse

from uber import receipt_items
from uber.config import c
from uber.custom_tags import email_only
from uber.decorators import ajax, all_renderable, not_site_mappable, check_if_can_reg, credit_card, csrf_protected, id_required, log_pageview, \
    redirect_if_at_con_to_kiosk, render, requires_account
from uber.errors import HTTPRedirect
from uber.models import Attendee, AttendeeAccount, Attraction, Email, Group, ModelReceipt, PromoCode, PromoCodeGroup, \
                        ReceiptTransaction, SignedDocument, Tracking
from uber.tasks.email import send_email
from uber.utils import prepare_saml_request
    

@all_renderable(public=True)
class Root:
    @not_site_mappable
    def acs(self, session, **params):
        req = prepare_saml_request(cherrypy.request)
        auth = OneLogin_Saml2_Auth(req, c.SAML_SETTINGS)
        auth.process_response()
        errors = auth.get_errors()
        if not errors:
            if auth.is_authenticated():
                account_email = auth.get_nameid()
                admin_account = None
                account = None

                try:
                    admin_account = session.get_admin_account_by_email(account_email)
                    cherrypy.session['account_id'] = admin_account.id
                except NoResultFound:
                    pass

                try:
                    account = session.get_attendee_account_by_email(account_email)
                    cherrypy.session['attendee_account_id'] = account.id
                except NoResultFound:
                    pass

                saml_data = auth.get_attributes()

                if not admin_account and not account:
                    raise HTTPRedirect("../landing/index?message=No account found for email {}", account_email)
                elif admin_account:
                    admin_account.attendee.first_name = saml_data.get("firstName", admin_account.attendee.first_name)
                    admin_account.attendee.last_name = saml_data.get("lastName", admin_account.attendee.last_name)
                    session.add(admin_account.attendee)

                log.debug(saml_data)
                redirect_url = req['post_data'].get('RelayState', '')
                
                if redirect_url:
                    if OneLogin_Saml2_Utils.get_self_url(req) != redirect_url:
                        redirect_url = None
                    else:
                        our_netloc = urlparse(c.URL_BASE).netloc
                        redirect_netloc = urlparse(redirect_url).netloc
                        if redirect_netloc and our_netloc != redirect_netloc:
                            log.error("SAML authentication used invalid redirect URL: {}".format(redirect_url))
                            redirect_url = None
                
                if not redirect_url:
                    if not admin_account:
                        redirect_url = "../preregistration/homepage"
                    elif not account:
                        redirect_url = "../accounts/homepage"
                    else:
                        redirect_url = "../landing/login_select"

                raise HTTPRedirect(redirect_url)
            else:
                raise HTTPRedirect("../landing/index?message={}", "Authentication unsuccessful.")
        else:
            log.error("Error when processing SAML Response: %s %s" % (', '.join(errors), auth.get_last_error_reason()))
            raise HTTPRedirect("../landing/index?message={}", "Authentication error: %s" % auth.get_last_error_reason())

    @not_site_mappable
    def metadata(self, **params):
        saml_settings = OneLogin_Saml2_Settings(settings=c.SAML_SETTINGS, sp_validation_only=True)
        metadata = saml_settings.get_sp_metadata()
        errors = saml_settings.validate_metadata(metadata)
        if len(errors) == 0:
            cherrypy.response.headers["Content-Type"] = "text/xml; charset=utf-8"
            return metadata
        else:
            error_msg = "Error found on SAML Metadata: %s" % (', '.join(errors))
            log.error(error_msg)
            return error_msg

    @not_site_mappable
    def logout(self, session, **params):
        req = prepare_saml_request(cherrypy.request)
        auth = OneLogin_Saml2_Auth(req)
        delete_session_callback = lambda: cherrypy.session.flush()
        url = auth.process_slo(delete_session_cb=delete_session_callback)
        errors = auth.get_errors()
        if len(errors) == 0:
            if url is not None:
                # To avoid 'Open Redirect' attacks, before execute the redirection confirm
                # the value of the url is a trusted URL.
                raise HTTPRedirect(url)
            else:
                log.debug("Successfully Logged out")
        else:
            log.error("Error when processing SLO: %s %s" % (', '.join(errors), auth.get_last_error_reason()))