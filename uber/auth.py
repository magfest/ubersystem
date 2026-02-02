import time
import cherrypy
import threading
import requests
import traceback
import logging
from jose import jwt, jwk
from sqlalchemy.orm.exc import NoResultFound

from uber.config import c
from uber.errors import HTTPRedirect
from uber.models import Attendee, AccessGroup, Session
from uber.utils import normalize_email_legacy

log = logging.getLogger(__name__)

class OIDC(cherrypy.Tool):
    def __init__(self):
        super().__init__('before_handler', self.do_before_request, priority=60)
        self.key_fetch_time = 0
        self.jwks_keys = {}
        self.key_lock = threading.Lock()
        
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
        if not claims:
            return None
        email = claims.get('email', None)
        if not email:
            return None

        with Session() as session:
            matching_attendee = session.query(Attendee).filter_by(
                is_valid=True, normalized_email=normalize_email_legacy(email)).first()

            try:
                admin_account = session.get_admin_account_by_email(email)
            except:
                if c.DEV_BOX:
                    if not matching_attendee:
                        matching_attendee = Attendee(placeholder=True, email=email)
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
            return admin_account.id
    
    def _get_attendee_account_for_claims(self, claims):
        if not claims:
            return None
        email = claims.get('email', None)
        if not email:
            return None
        
        with Session() as session:
            try:
                account = session.get_attendee_account_by_email(email)
            except NoResultFound:
                all_matching_attendees = session.query(Attendee).filter_by(
                    normalized_email=normalize_email_legacy(email)).all()
                if all_matching_attendees:
                    account = session.create_attendee_account(email)
                    for attendee in all_matching_attendees:
                        session.add_attendee_to_account(attendee, account)
            return account.id
    
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
        cherrypy.request.admin_account = self._get_admin_account_for_claims(claims)
        cherrypy.request.attendee_account = self._get_attendee_account_for_claims(claims)
        
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
        claims = self._verify_token(token)
        if refresh_token and not claims:
            claims = self.handle_login(refresh_token=refresh_token)
            
        cherrypy.request.admin_account = self._get_admin_account_for_claims(claims)
        cherrypy.request.attendee_account = self._get_attendee_account_for_claims(claims)
            
cherrypy.tools.oidc = OIDC()