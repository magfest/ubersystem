import time
import cherrypy
import requests
import logging
from jose import jwt, jwk
from jose.utils import base64url_decode
from sqlalchemy.orm.exc import NoResultFound

from uber.config import c
from uber.decorators import all_renderable
from uber.errors import HTTPRedirect
from uber.models import Attendee, AccessGroup
from uber.utils import prepare_saml_request, normalize_email_legacy

log = logging.getLogger(__name__)

key_fetch_time = 0
jwks_keys = {}

def _fetch_key(kid):
    """
    Retrieve a key from Keycloak by kid
    Won't request new keys more often than every 60s
    """
    global jwks_keys, key_fetch_time
    if kid in jwks_keys:
        return jwks_keys[kid]
    elif time.time() - key_fetch_time < 60:
        return None
    key_fetch_time = time.time()
    oidc_config = requests.get(c.OIDC_METADATA_URL).json()
    jwks_uri = oidc_config['jwks_uri']
    
    keys = requests.get(jwks_uri).json()['keys']
    jwks_keys = {key['kid']: key for key in keys}
    log.info(f"Loaded {len(jwks_keys)} public keys from {c.OIDC_METADATA_URL}")
    return jwks_keys.get(kid, None)

def _verify_token(token):
    """
    Cryptographically verifies the JWT signature using Keycloak's public keys.
    Returns the decoded payload if valid, raises Exception if not.
    """
    # Get the header to find the Key ID (kid)
    headers = jwt.get_unverified_header(token)
    kid = headers.get('kid')
    
    # Find the matching public key in our cache
    key_data = _fetch_key(kid)
    if not key_data:
        raise HTTPRedirect("../landing/index?message={}", "Where did you get this auth token?")

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

@all_renderable(public=True)
class Root:    
    def callback(self, session, code=None, error=None, **kwargs):
        if error:
            raise HTTPRedirect("../landing/index?message={}", f"Error: {error}")

        payload = {
            'grant_type': 'authorization_code',
            'client_id': c.OIDC_CLIENT_ID,
            'client_secret': c.OIDC_CLIENT_SECRET,
            'code': code,
            'redirect_uri': c.OIDC_REDIRECT_URL
        }
        
        response = requests.post(c.OIDC_TOKEN_ENDPOINT, data=payload)
        response.raise_for_status()
        token_response = response.json()
        
        # We use the ID Token for identity verification (Standard OIDC)
        id_token = token_response.get('id_token')
        if not id_token:
            raise HTTPRedirect("../landing/index?message={}", "No auth token.")

        claims = _verify_token(id_token)
        
        email = claims.get('email')
        if not email:
            raise HTTPRedirect("../landing/index?message={}", "You have a valid token, but it doesn't have your email. Who are you?")

        admin_account = None
        account = None
        matching_attendee = session.query(Attendee).filter_by(
            is_valid=True, normalized_email=normalize_email_legacy(email)).first()
        message = "We could not find any accounts from the email {}. "\
            "Please contact your administrator.".format(email)

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
        if admin_account:
            cherrypy.response.cookie['session_token'] = token_response
            cherrypy.response.cookie['session_token']['path'] = '/'
            cherrypy.response.cookie['session_token']['max-age'] = c.OIDC_SESSION_EXPIRATION
            cherrypy.response.cookie['session_token']['httponly'] = True

            cherrypy.session['account_id'] = admin_account.id
            raise HTTPRedirect("../accounts/homepage")
        
        try:
            account = session.get_attendee_account_by_email(email)
        except NoResultFound:
            all_matching_attendees = session.query(Attendee).filter_by(
                normalized_email=normalize_email_legacy(email)).all()
            if all_matching_attendees:
                account = session.create_attendee_account(email)
                for attendee in all_matching_attendees:
                    session.add_attendee_to_account(attendee, account)
            else:
                message = "We could not find any registrations matching the email {}.".format(email)

        if account:
            cherrypy.response.cookie['session_token'] = token_response
            cherrypy.response.cookie['session_token']['path'] = '/'
            cherrypy.response.cookie['session_token']['max-age'] = c.OIDC_SESSION_EXPIRATION
            cherrypy.response.cookie['session_token']['httponly'] = True
            
            cherrypy.session['attendee_account_id'] = account.id
            raise HTTPRedirect("../preregistration/homepage")
        raise HTTPRedirect("../landing/index?message={}", message)

    def login(self):
        # scope=openid is required to get the ID Token
        params = (
            f"?client_id={c.OIDC_CLIENT_ID}"
            f"&response_type=code"
            f"&scope=openid email"
            f"&redirect_uri={c.OIDC_REDIRECT_URL}"
        )
        raise HTTPRedirect(c.OIDC_AUTH_ENDPOINT + params)
    
    def refresh_token(self):
        if not 'session_token' in cherrypy.request.cookie:
            return
        tokens = cherrypy.request.cookie['session_token'].value
        if not tokens or 'refresh_token' not in tokens:
            raise cherrypy.HTTPRedirect("/login")

        token_endpoint = self.oidc_config['token_endpoint']
        payload = {
            'grant_type': 'refresh_token',
            'client_id': c.OIDC_CLIENT_ID,
            'client_secret': c.OIDC_CLIENT_SECRET,
            'refresh_token': tokens['refresh_token']
        }

        try:
            response = requests.post(token_endpoint, data=payload)
            if response.status_code == 200:
                new_tokens = response.json()
                cherrypy.response.cookie['session_token'] = new_tokens
                cherrypy.response.cookie['session_token']['path'] = '/'
                cherrypy.response.cookie['session_token']['max-age'] = c.OIDC_SESSION_EXPIRATION
                cherrypy.response.cookie['session_token']['httponly'] = True
                
                self._process_login(tokens)
                raise cherrypy.HTTPRedirect("/")
            else:
                cherrypy.session.clear()
                raise cherrypy.HTTPRedirect("/login")
                
        except cherrypy.HTTPRedirect:
            raise
        except Exception as e:
            return f"Refresh Error: {str(e)}"
