import cherrypy

from pockets.autolog import log
from sqlalchemy.orm.exc import NoResultFound

# xmlsec moved their constants but onelogin hasn't updated to match yet
# This monkey patches the RSA_SHA256 constant into where onelogin looks for it
import xmlsec
class NS: pass
xmlsec.Transform = NS
xmlsec.Transform.RSA_SHA256 = xmlsec.constants.TransformRsaSha256
from onelogin.saml2.auth import OneLogin_Saml2_Auth
from onelogin.saml2.settings import OneLogin_Saml2_Settings
from onelogin.saml2.utils import OneLogin_Saml2_Utils
from urllib.parse import urlparse

from uber.config import c
from uber.decorators import all_renderable, not_site_mappable
from uber.errors import HTTPRedirect
from uber.models import Attendee, AccessGroup
from uber.utils import prepare_saml_request, normalize_email_legacy


@all_renderable(public=True)
class Root:
    @not_site_mappable
    def acs(self, session, **params):
        req = prepare_saml_request(cherrypy.request)
        auth = OneLogin_Saml2_Auth(req, c.SAML_SETTINGS)
        auth.process_response()

        assertion_id = auth.get_last_assertion_id()

        errors = auth.get_errors()
        if not errors:
            if c.REDIS_STORE.hget(c.REDIS_PREFIX + 'processed_saml_assertions', assertion_id):
                log.error("Existing SAML assertion was replayed: {}. "
                          "This is either an attack, a programming error, or someone tried to log in while the server was down.".format(assertion_id))
                raise HTTPRedirect("../landing/index?message={}", "Authentication unsuccessful.")

            c.REDIS_STORE.hset(c.REDIS_PREFIX + 'processed_saml_assertions', assertion_id,
                               auth.get_last_assertion_not_on_or_after())

            if auth.is_authenticated():
                account_email = auth.get_nameid()
                admin_account = None
                account = None
                matching_attendee = session.query(Attendee).filter_by(
                    is_valid=True, normalized_email=normalize_email_legacy(account_email)).first()
                message = "We could not find any accounts from the email {}. "\
                    "Please contact your administrator.".format(account_email)

                try:
                    admin_account = session.get_admin_account_by_email(account_email)
                except NoResultFound:
                    if c.DEV_BOX:
                        if not matching_attendee:
                            matching_attendee = Attendee(placeholder=True, email=account_email)
                            session.add(matching_attendee)
                            session.commit()

                        admin_account, pwd = session.create_admin_account(matching_attendee, generate_pwd=False)
                        all_access_group = session.query(AccessGroup).filter_by(name="All Access").first()
                        if not all_access_group:
                            all_access_group = AccessGroup(
                                name='All Access',
                                access={section: '5' for section in c.ADMIN_PAGES}
                            )
                            session.add(all_access_group)

                        admin_account.access_groups.append(all_access_group)
                        session.commit()
                if admin_account:
                    cherrypy.session['account_id'] = admin_account.id

                try:
                    account = session.get_attendee_account_by_email(account_email)
                except NoResultFound:
                    all_matching_attendees = session.query(Attendee).filter_by(
                        normalized_email=normalize_email_legacy(account_email)).all()
                    if all_matching_attendees:
                        account = session.create_attendee_account(account_email)
                        for attendee in all_matching_attendees:
                            session.add_attendee_to_account(attendee, account)
                    else:
                        message = "We could not find any registrations matching the email {}.".format(account_email)

                if account:
                    cherrypy.session['attendee_account_id'] = account.id

                if not admin_account and not account:
                    raise HTTPRedirect("../landing/index?message={}", message)

                # Forcibly exit any volunteer kiosks that were running
                cherrypy.session.pop('kiosk_operator_id', None)
                cherrypy.session.pop('kiosk_supervisor_id', None)

                if admin_account:
                    attendee_to_update = admin_account.attendee
                else:
                    attendee_to_update = matching_attendee

                if attendee_to_update:
                    saml_data = auth.get_attributes()
                    attendee_to_update.first_name = saml_data.get("firstName", [attendee_to_update.first_name])[0]
                    attendee_to_update.last_name = saml_data.get("lastName", [attendee_to_update.last_name])[0]
                    session.add(attendee_to_update)

                session.commit()

                redirect_url = req['post_data'].get('RelayState', '')

                if redirect_url:
                    if OneLogin_Saml2_Utils.get_self_url(req) != redirect_url:
                        our_netloc = urlparse(c.URL_ROOT).netloc
                        redirect_netloc = urlparse(redirect_url).netloc
                        if not redirect_netloc or redirect_netloc != our_netloc:
                            log.error("SAML authentication used invalid redirect URL: {}".format(redirect_url))
                            redirect_url = None
                        if redirect_url and 'accounts' in redirect_url and not admin_account:
                            # Prevents a redirect loop if someone tries to log in as an admin with no admin account
                            redirect_url = None

                if not redirect_url:
                    if c.AT_OR_POST_CON and admin_account:
                        redirect_url = "../accounts/homepage"
                    else:
                        redirect_url = "../preregistration/homepage"

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
