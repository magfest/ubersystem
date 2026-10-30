# Attendee-PII boundary: this module returns personal data to third-party apps through the
# self_lookup API. Adding a field to LIST_FIELDS or DETAIL_FIELDS widens what every Self token
# can read; review it as a data-sharing change. Every query here is scoped to the badges
# linked to one OIDC subject (`sub`) through an AttendeeAccount or an AdminAccount.
import uuid

import cherrypy
from cherrypy import HTTPError
from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload

from uber.config import c
from uber.models import AdminAccount, ApiToken, Attendee, AttendeeAccount, Shift

LIST_FIELDS = {
    'id': True,
    'badge_num': True,
    'badge_type_label': True,
    'badge_status_label': True,
    'full_name': True,
    'staffing': True,
    'ribbon_labels': True,
    'group': {'name': True},
}

DETAIL_FIELDS = dict(LIST_FIELDS, **{
    'badge_printed_name': True,
    'checked_in': True,
    'is_dept_head': True,
    'amount_unpaid': True,
    'weighted_hours': True,
    'worked_hours': True,
})


def _blank(sub):
    # Accounts that never signed in through SSO store sso_id as '', so a blank sub would match all of them.
    return not isinstance(sub, str) or not sub.strip()


def badge_set_query(session, sub):
    """Return valid badges linked to `sub` through an attendee account or an admin account."""
    if _blank(sub):
        return session.query(Attendee).filter(False)
    via_account = (select(Attendee.id).join(Attendee.managers).where(AttendeeAccount.sso_id == sub))
    via_admin = select(AdminAccount.attendee_id).where(AdminAccount.sso_id == sub)
    return (session.query(Attendee)
            .filter(Attendee.is_valid, or_(Attendee.id.in_(via_account), Attendee.id.in_(via_admin)))
            .options(selectinload(Attendee.dept_memberships), selectinload(Attendee.shifts).selectinload(Shift.job),
                     selectinload(Attendee.group)))


def is_linked(session, sub):
    """Return whether any attendee or admin account carries `sub`."""
    if _blank(sub):
        return False
    return bool(session.query(AttendeeAccount.id).filter(AttendeeAccount.sso_id == sub).first()
                or session.query(AdminAccount.id).filter(AdminAccount.sso_id == sub).first())


def list_badges(session, sub):
    badges = [_public(a, LIST_FIELDS) for a in badge_set_query(session, sub)]
    return {'linked': is_linked(session, sub), 'badges': badges}


def badge_detail(session, sub, attendee_id):
    """Return one badge with department data. A malformed ID and a foreign ID both raise the same 404."""
    try:
        badge_id = str(uuid.UUID(str(attendee_id)))
    except ValueError:
        raise HTTPError(404, 'Badge not found')
    attendee = badge_set_query(session, sub).filter(Attendee.id == badge_id).first()
    if not attendee:
        raise HTTPError(404, 'Badge not found')
    return dict(_public(attendee, DETAIL_FIELDS), **attendee.dept_summary)


def _public(attendee, fields):
    # Attendee.to_dict ignores the nested spec for a single related model and returns all of its
    # columns, so related models are serialized here with their own field list.
    flat = {k: v for k, v in fields.items() if not isinstance(v, dict)}
    data = attendee.to_dict(flat)
    for name, sub_fields in fields.items():
        if isinstance(sub_fields, dict):
            related = getattr(attendee, name)
            data[name] = {k: getattr(related, k) for k in sub_fields} if related else None
    return data


def authenticated_sub(session, headers):
    """Return the OIDC subject that a request may read, or raise HTTPError.

    The request needs an unrevoked Self-level API token and a bearer access token issued to the client bound to it.
    """
    # Permission boundary: api_auth also admits a logged-in admin session, so this function checks the
    # presented API token for the Self level itself. The client check stops an app from replaying a token
    # that the provider issued to a different client.
    if not c.OIDC_API_AUDIENCE:
        raise HTTPError(503, 'Self lookup is not configured')

    try:
        token_id = str(uuid.UUID(str(headers.get('X-Auth-Token', ''))))
    except ValueError:
        raise HTTPError(403, 'Self lookup requires an API token')
    api_token = session.query(ApiToken).filter_by(token=token_id).first()
    if not api_token or api_token.revoked_time or not api_token.api_self:
        raise HTTPError(403, 'Self lookup requires an API token')

    scheme, _, bearer = (headers.get('Authorization') or '').strip().partition(' ')
    bearer = bearer.strip()
    if scheme.lower() != 'bearer' or not bearer:
        raise HTTPError(401, 'A bearer access token is required')

    claims = cherrypy.tools.oidc._verify_token(bearer, audience=c.OIDC_API_AUDIENCE)
    if not claims:
        raise HTTPError(401, 'Invalid access token')

    client_id = (api_token.oidc_client_id or '').strip()
    # Keycloak, Auth0, and Entra ID name the client in azp; RFC 9068 access tokens use client_id.
    # As of October 2026, Okta access tokens use a non-standard cid claim, which is not read; Okta apps get a 403.
    issued_to = claims.get('azp') or claims.get('client_id')
    if not client_id or issued_to != client_id:
        raise HTTPError(403, 'Access token was not issued to this API token\'s client')

    sub = claims.get('sub')
    if _blank(sub):
        raise HTTPError(401, 'Access token has no subject')
    return sub
