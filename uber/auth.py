import time
import base64
import cherrypy
import threading
import requests
import traceback
import logging
import secrets
from jose import jwt, jwk
from sqlalchemy.orm.exc import NoResultFound
from urllib.parse import urlparse, parse_qsl

from uber.email import EmailService
from uber.config import c
from uber.custom_tags import email_only
from uber.errors import HTTPRedirect
from uber.decorators import render
from uber.models import Attendee, AdminAccount, AttendeeAccount, AccessGroup, Session, PasswordReset
from uber.tasks.email import send_email
from uber.utils import normalize_email_legacy

log = logging.getLogger(__name__)

class OIDC(cherrypy.Tool):
    def __init__(self):
        super().__init__('before_handler', self.do_before_request, priority=60)
        self.key_fetch_time = 0
        self.jwks_keys = {}
        self.key_lock = threading.Lock()

    @classmethod
    def send_claim_token(cls, session, attendee_account, admin_account=None):
        if attendee_account and attendee_account.password_reset:
            session.delete(attendee_account.password_reset)
        elif admin_account and admin_account.password_reset:
            session.delete(admin_account.password_reset)
        session.commit()

        token = secrets.token_urlsafe(64)
        session.add(PasswordReset(attendee_account=attendee_account, admin_account=admin_account, token=token))
        session.commit()

        EmailService.queue_email(session, 'sso_account_setup', attendee_account,
                                 data={'admin_account': admin_account, 'token': token})

    @classmethod
    def process_account_claim_token(cls, session, account_claim_token, sso_id=None, existing_account=None, dry_run=False):
        # Validates and processes our SSO account claim token, including merging with an existing account if there is one
        message = ''
        attendee_account = session.query(AttendeeAccount).join(AttendeeAccount.password_reset).filter(
                PasswordReset.token == account_claim_token).first()
        admin_account = session.query(AdminAccount).join(AdminAccount.password_reset).filter(
                PasswordReset.token == account_claim_token).first()
        
        accounts_pluralized = 'these accounts' if attendee_account and admin_account else 'this account'
        
        if attendee_account and attendee_account.sso_id:
            session.delete(attendee_account.password_reset)
            if sso_id and sso_id == attendee_account.sso_id:
                message = f"You have already claimed {accounts_pluralized}."
            attendee_account = None
        if admin_account and admin_account.sso_id:
            session.delete(admin_account.password_reset)
            if sso_id and sso_id == admin_account.sso_id:
                message = f"You have already claimed {accounts_pluralized}."
            admin_account = None

        if not attendee_account and not admin_account:
            message = "Invalid claim link. This link may have already been used."
        elif existing_account and admin_account and any(attendee for attendee in existing_account.attendees if attendee.admin_account):
            message = f"You cannot have more than one admin account associated with your {c.OIDC_ACCOUNT_NAME} for this event."
        elif (sso_id or existing_account) and not cherrypy.session.get('oidc_email_verified'):
            message = f"Please verify the email on your {c.OIDC_ACCOUNT_NAME} account to claim {accounts_pluralized}."
        elif attendee_account and attendee_account.password_reset.is_expired:
            OIDC.send_claim_token(session, attendee_account, admin_account)
            message = "This claim link has expired. Please check your email inbox for a new claim link."
        elif attendee_account:
            for attendee in attendee_account.attendees:
                if attendee.admin_account and attendee.admin_account.sso_id and sso_id and attendee.admin_account.sso_id != sso_id:
                        message = f"Your account has been set up incorrectly. Please contact us at {email_only(c.CONTACT_EMAIL)}."
        
        if message:
            raise ValueError(message or "Invalid claim link. This link may have already been used.")
        
        if sso_id and not dry_run:
            if admin_account:
                admin_account.sso_id = sso_id
                session.delete(admin_account.password_reset)
            if attendee_account:
                if existing_account:
                    duplicate_account = attendee_account
                    for attendee in duplicate_account.attendees:
                        session.add_attendee_to_account(attendee, existing_account)
                    session.delete(duplicate_account)
                    attendee_account = existing_account
                else:
                    attendee_account.sso_id = sso_id
                    session.delete(attendee_account.password_reset)

                for attendee in attendee_account.attendees:
                    if attendee.admin_account:
                        attendee.admin_account.sso_id = sso_id
                        if attendee.admin_account.password_reset:
                            session.delete(attendee.admin_account.password_reset)
                        session.add(attendee.admin_account)
            session.commit()

            cherrypy.request.attendee_account = getattr(attendee_account, 'id', None)
            cherrypy.request.admin_account = getattr(admin_account, 'id', None)
        return attendee_account, admin_account

    def _fetch_key(self, kid):
        """
        Retrieve a key from Keycloak by kid
        Won't request new keys more often than every 60s
        """
        try:
            with self.key_lock:
                if kid in self.jwks_keys:
                    return self.jwks_keys[kid]
                elif time.time() - self.key_fetch_time < 60:
                    return None
                self.key_fetch_time = time.time()
                oidc_config = requests.get(c.OIDC_METADATA_URL).json()
                jwks_uri = oidc_config['jwks_uri']
                
                keys = requests.get(jwks_uri).json()['keys']
                self.jwks_keys = {key['kid']: key for key in keys}
                log.info(f"Loaded {len(self.jwks_keys)} public keys from {c.OIDC_METADATA_URL}")
                return self.jwks_keys.get(kid, None)
        except:
            traceback.print_exc()
            return None

    def _verify_token(self, token):
        """
        Cryptographically verifies the JWT signature using Keycloak's public keys.
        Returns the decoded payload if valid, raises Exception if not.
        """
        try:
            # Get the header to find the Key ID (kid)
            headers = jwt.get_unverified_header(token)
            kid = headers.get('kid')
            
            # Find the matching public key in our cache
            key_data = self._fetch_key(kid)
            if not key_data:
                return False

            # Construct the public key object
            public_key = jwk.construct(key_data)

            # Verify signature, audience, and expiration
            # We verify the 'id_token', so the audience must be OUR Client ID.
            payload = jwt.decode(
                token,
                public_key,
                algorithms=['RS256'],
                audience=c.OIDC_CLIENT_ID,
                options={"verify_at_hash": False}
            )
            return payload
        except:
            traceback.print_exc()
            return None
        
    def _get_admin_account_for_claims(self, claims):
        if not claims or not claims.get('sub', None):
            return

        with Session() as session:
            account = session.query(AdminAccount).filter(AdminAccount.sso_id == claims['sub']).first()
            return account.id if account else None

    def _get_attendee_account_for_claims(self, claims):
        if not claims or not claims.get('sub', None):
            return None

        with Session() as session:
            account = session.query(AttendeeAccount).filter(AttendeeAccount.sso_id == claims['sub']).first()
            return account.id if account else None

    def _init_accounts_from_claims(self, claims):
        roles = claims.get('realm_access', {}).get('roles', [])
        email = claims.get('workspace_email', claims.get('email', ''))
        sso_id = claims.get('sub', None)
        admin_account = None

        with Session() as session:
            attendee_account = session.create_attendee_account(email)
            attendee_account.sso_id = sso_id
            session.add(attendee_account)
            if email and c.DEV_BOX and ('staff' in roles or 'all-access' in roles):
                # If it's the first login from this account on a test server, and we're staff,
                # auto-provision an attendee and admin account
                matching_attendee = session.query(Attendee).filter_by(
                    is_valid=True, normalized_email=normalize_email_legacy(email)).first()
                if not matching_attendee:
                    matching_attendee = Attendee(placeholder=True, email=email,
                                                first_name=claims.get('given_name', 'Test'),
                                                last_name=claims.get('family_name', 'Staff'))
                    session.add(matching_attendee)
                session.add_attendee_to_account(matching_attendee, attendee_account)
                session.commit()

                admin_account = matching_attendee.admin_account
                if not admin_account:
                    admin_account, pwd = session.create_admin_account(matching_attendee, generate_pwd=False)
                    all_access_group = session.query(AccessGroup).filter_by(name="All Access").first()
                    if not all_access_group:
                        all_access_group = AccessGroup(
                            name='All Access',
                            access={section: '5' for section in c.ADMIN_PAGES}
                        )
                        session.add(all_access_group)

                    admin_account.access_groups.append(all_access_group)
                admin_account.sso_id = sso_id
            session.commit()
            return attendee_account.id, getattr(admin_account, 'id', None)
    
    def _exchange_code_for_tokens(self, code, redirect_uri=c.OIDC_REDIRECT_URL):
        """
        Take the code received on our callback and exchange it for a JWT
        DOES NOT VERIFY THE JWT!
        """
        try:
            payload = {
                'grant_type': 'authorization_code',
                'client_id': c.OIDC_CLIENT_ID,
                'client_secret': c.OIDC_CLIENT_SECRET,
                'code': code,
                'redirect_uri': redirect_uri
            }

            response = requests.post(c.OIDC_TOKEN_ENDPOINT, data=payload)
            response.raise_for_status()
            return response.json()
        except:
            traceback.print_exc()
            return None
    
    def _refresh_token(self, code):
        """
        Get a new token by using a refresh_token
        DOES NOT VERIFY THE JWT!
        """
        try:
            payload = {
                'grant_type': 'refresh_token',
                'client_id': c.OIDC_CLIENT_ID,
                'client_secret': c.OIDC_CLIENT_SECRET,
                'refresh_token': code
            }

            response = requests.post(c.OIDC_TOKEN_ENDPOINT, data=payload)
            response.raise_for_status()
            return response.json()
        except:
            traceback.print_exc()
            return None

    def handle_login(self, code=None, refresh_token=None, redirect_uri=c.OIDC_REDIRECT_URL, account_claim_token=None):
        tokens = self._exchange_code_for_tokens(code, redirect_uri=redirect_uri)
        if not tokens:
            tokens = self._refresh_token(refresh_token)
        if not tokens:
            return "Login failed."
        claims = self._verify_token(tokens.get('id_token', None))
        sso_id = claims.get('sub', None)
        if not sso_id:
            return "No account ID provided. Please contact your developer."
        cherrypy.session['oidc_email_verified'] = claims.get('email_verified', False)
        cherrypy.request.attendee_account = self._get_attendee_account_for_claims(claims)
        cherrypy.request.admin_account = self._get_admin_account_for_claims(claims)

        if not cherrypy.request.attendee_account and not cherrypy.request.admin_account:
            if account_claim_token:
                try:
                    with Session() as session:
                        OIDC.process_account_claim_token(session, account_claim_token, sso_id)
                    if cherrypy.request.attendee_account or cherrypy.request.admin_account:
                        cherrypy.request.redirect_url = '../preregistration/homepage?message=Thank you for setting up your account!'
                except ValueError as e:
                    return e
            else:
                cherrypy.request.attendee_account, cherrypy.request.admin_account = self._init_accounts_from_claims(claims)
        
        if cherrypy.request.attendee_account or cherrypy.request.admin_account:
            cherrypy.response.cookie['session_token'] = tokens['id_token']
            cherrypy.response.cookie['session_token']['path'] = '/'
            cherrypy.response.cookie['session_token']['max-age'] = tokens['expires_in']
            cherrypy.response.cookie['session_token']['httponly'] = True

            if claims.get('workspace_email'):
                cherrypy.response.cookie['idp_hint'] = 'google-workspace'
                cherrypy.response.cookie['idp_hint']['max-age'] = 21600  # 6 hours
                cherrypy.response.cookie['idp_hint']['path'] = '/'
                cherrypy.response.cookie['idp_hint']['httponly'] = True
            else:
                cherrypy.response.cookie['idp_hint'] = ''
                cherrypy.response.cookie['idp_hint']['expires'] = 0
                cherrypy.response.cookie['idp_hint']['max-age'] = 0
                cherrypy.response.cookie['idp_hint']['path'] = '/'
            
            if 'refresh_token' in tokens:
                cherrypy.response.cookie['refresh_token'] = tokens['refresh_token']
                cherrypy.response.cookie['refresh_token']['path'] = '/'
                cherrypy.response.cookie['refresh_token']['max-age'] = tokens['refresh_expires_in']
                cherrypy.response.cookie['refresh_token']['httponly'] = True

    def redirect_to_keycloak(self, target_url=None):
        params = (
            f"?client_id={c.OIDC_CLIENT_ID}"
            f"&response_type=code"
            f"&scope=openid email"
            f"&redirect_uri={c.OIDC_REDIRECT_URL}"
        )

        # Build the post_login_url URL parameter so we can redirect back to the right page
        # We base64 encode it to isolate it from other URL parameters generated by the IdP
        current_path = target_url
        if current_path is None:
            current_path = cherrypy.url(qs=cherrypy.request.query_string)

        if current_path:
            params += f"?post_login_url={base64.urlsafe_b64encode(current_path.encode()).decode()}"

        if 'idp_hint' in cherrypy.request.cookie:
            params += f"&kc_idp_hint={cherrypy.request.cookie['idp_hint'].value}"

        raise HTTPRedirect(c.OIDC_AUTH_ENDPOINT + params)

    def do_before_request(self):
        if 'state' in cherrypy.request.params:
            try:
                oidc_state = base64.urlsafe_b64decode(cherrypy.request.params['state'].encode()).decode()
                params = dict(parse_qsl(urlparse(oidc_state).query))
                for key, val in params.items():
                    cherrypy.request.params[key] = val
            except base64.binascii.Error:
                pass
        token = cherrypy.request.cookie['session_token'].value if 'session_token' in cherrypy.request.cookie else None
        refresh_token = cherrypy.request.cookie['refresh_token'].value if 'refresh_token' in cherrypy.request.cookie else None
        if not token and not refresh_token:
            return
        claims = self._verify_token(token)
        if refresh_token and not claims:
            self.handle_login(refresh_token=refresh_token)
        else:
            cherrypy.request.attendee_account = self._get_attendee_account_for_claims(claims)
            cherrypy.request.admin_account = self._get_admin_account_for_claims(claims)
            
cherrypy.tools.oidc = OIDC()