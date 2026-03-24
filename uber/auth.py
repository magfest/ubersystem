import time
import bcrypt
import cherrypy
import threading
import requests
import traceback
import logging
import secrets
from jose import jwt, jwk
from sqlalchemy.orm.exc import NoResultFound

from uber.config import c
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
        self.error = ''

    def send_claim_token(self, session, attendee_account=None, admin_account=None):
        if not attendee_account and not admin_account:
            return

        if attendee_account and attendee_account.password_reset:
            session.delete(attendee_account.password_reset)
        elif admin_account and admin_account.password_reset:
            session.delete(admin_account.password_reset)

        email = attendee_account.email if attendee_account else admin_account.attendee.email

        token = secrets.token_urlsafe(64)
        session.add(PasswordReset(attendee_account=attendee_account, admin_account=admin_account, token=token))
        body = render('emails/accounts/new_sso_account.html', {
            'attendee_account': attendee_account, 'admin_account': admin_account, 'token': token}, encoding=None)
        send_email.delay(
            c.ADMIN_EMAIL,
            email,
            c.EVENT_NAME + ' Account Setup',
            body,
            format='html',
            model=(attendee_account or admin_account).to_dict('id'))
        
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
                log.error(oidc_config)
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
        if not claims:
            return
        
        sso_id = claims.get('sub', None)
        if not sso_id:
            self.error = "No account ID provided. Please contact your developer."
            return

        email_verified = claims.get('email_verified', None)
        claim_token = claims.get('claim_token', None)

        with Session() as session:
            claimed_account = session.query(AdminAccount).filter(AdminAccount.sso_id == sso_id).first()
            if claimed_account:
                return claimed_account.id

            if not claim_token:
                return

            claim_token_account = session.query(AdminAccount).join(AdminAccount.password_reset).filter(
                PasswordReset.hashed == claim_token).first()
            
            if not claim_token_account:
                return
            
            if claim_token_account.sso_id:
                self.error = "This admin account has already been claimed."
                return
            
            if email_verified is False:
                self.error = f"Please verify the email on your {c.OIDC_ACCOUNT_NAME} account to claim your admin account."
                return
            
            if not claim_token_account.password_reset or claim_token_account.password_reset.is_expired:
                attendee_account = claim_token_account.password_reset.attendee_account if claim_token_account.password_reset else None
                self.send_claim_token(session, attendee_account, claim_token_account)
                self.error = "This claim link has expired. Please check your email inbox for a new claim link."
                return
            
            claim_token_account.sso_id = sso_id
            return claim_token_account.id

    def _get_attendee_account_for_claims(self, claims):
        if not claims:
            return None

        sso_id = claims.get('sub', None)
        if not sso_id:
            self.error = "No account ID provided. Please contact your developer."
            return

        claim_token = claims.get('claim_token', None)
        email_verified = claims.get('email_verified', None)
        claim_token_account = None

        with Session() as session:
            claimed_account = session.query(AttendeeAccount).filter(AttendeeAccount.sso_id == sso_id).first()
            if claim_token:
                claim_token_account = session.query(AttendeeAccount).join(AttendeeAccount.password_reset).filter(
                    PasswordReset.hashed == claim_token).first()
                
                if not claim_token_account:
                    admin_claim_account = session.query(AdminAccount).join(AdminAccount.password_reset).filter(
                        PasswordReset.hashed == claim_token).first()
                    if not admin_claim_account:
                        self.error = "Invalid claim link. This link may have already been used or replaced."
                        return
                    elif claimed_account:
                        return claimed_account.id
                    else:
                        new_account = self._init_accounts_from_claims(session, claims)
                        return getattr(new_account, 'id')
                
                if claim_token_account.sso_id:
                    if claim_token_account.sso_id == sso_id:
                        return claim_token_account.id
                    self.error = "This account has already been claimed."
                    return
                
                if email_verified is False:
                    self.error = f"Please verify the email on your {c.OIDC_ACCOUNT_NAME} account to claim your account."
                    return

                if not claim_token_account.password_reset or claim_token_account.password_reset.is_expired:
                    admin_account = claim_token_account.password_reset.admin_account if claim_token_account.password_reset else None
                    self.send_claim_token(session, claim_token_account, admin_account)
                    self.error = "This claim link has expired. Please check your email inbox for a new claim link."
                    return
                
                claim_token_account.sso_id = sso_id

            if claimed_account:
                if claim_token_account:
                    for attendee in claim_token_account:
                        session.add_attendee_to_account(attendee, claimed_account)
                    session.delete(claim_token_account)
                return claimed_account.id
            elif not claim_token_account:
                new_account = self._init_accounts_from_claims(session, claims)
                return getattr(new_account, 'id')
            return claim_token_account

    def _init_accounts_from_claims(self, session, claims):
        roles = claims.get('realm_access', {}).get('roles', [])
        email = claims.get('workspace_email', claims.get('email', ''))
        sso_id = claims.get('sub', None)

        attendee_account = AttendeeAccount(email=email, sso_id=sso_id)
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
        return attendee_account
    
    def _exchange_code_for_tokens(self, code):
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
                'redirect_uri': c.OIDC_REDIRECT_URL
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

    def handle_login(self, code=None, refresh_token=None):
        tokens = self._exchange_code_for_tokens(code)
        if not tokens:
            tokens = self._refresh_token(refresh_token)
        if not tokens:
            return None
        claims = self._verify_token(tokens.get('id_token', None))
        cherrypy.request.attendee_account = self._get_attendee_account_for_claims(claims)
        cherrypy.request.admin_account = self._get_admin_account_for_claims(claims) if not self.error else None
        
        if cherrypy.request.admin_account or cherrypy.request.attendee_account:
            cherrypy.response.cookie['session_token'] = tokens['id_token']
            cherrypy.response.cookie['session_token']['path'] = '/'
            cherrypy.response.cookie['session_token']['max-age'] = tokens['expires_in']
            cherrypy.response.cookie['session_token']['httponly'] = True
            
            if 'refresh_token' in tokens:
                cherrypy.response.cookie['refresh_token'] = tokens['refresh_token']
                cherrypy.response.cookie['refresh_token']['path'] = '/'
                cherrypy.response.cookie['refresh_token']['max-age'] = tokens['refresh_expires_in']
                cherrypy.response.cookie['refresh_token']['httponly'] = True
        return claims
        
    def redirect_to_keycloak(self, target_url=None):
        # Store the current path in a transient cookie
        current_path = target_url
        if current_path is None:
            current_path = cherrypy.url(qs=cherrypy.request.query_string)
        cherrypy.response.cookie['post_login_url'] = current_path
        cherrypy.response.cookie['post_login_url']['path'] = '/'
        cherrypy.response.cookie['post_login_url']['max-age'] = 300
        cherrypy.response.cookie['post_login_url']['httponly'] = True
        
        params = (
            f"?client_id={c.OIDC_CLIENT_ID}"
            f"&response_type=code"
            f"&scope=openid email"
            f"&redirect_uri={c.OIDC_REDIRECT_URL}"
        )
        raise HTTPRedirect(c.OIDC_AUTH_ENDPOINT + params)

    def do_before_request(self):
        token = cherrypy.request.cookie['session_token'].value if 'session_token' in cherrypy.request.cookie else None
        refresh_token = cherrypy.request.cookie['refresh_token'].value if 'refresh_token' in cherrypy.request.cookie else None
        if not token and not refresh_token:
            return
        claims = self._verify_token(token)
        if refresh_token and not claims:
            self.handle_login(refresh_token=refresh_token)
        else:
            cherrypy.request.attendee_account = self._get_attendee_account_for_claims(claims)
            cherrypy.request.admin_account = self._get_admin_account_for_claims(claims) if not self.error else None
            
cherrypy.tools.oidc = OIDC()