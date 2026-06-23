import base64
import json
import secrets
import uuid
import cherrypy
import logging
from datetime import datetime, timedelta
from sqlalchemy.orm.exc import NoResultFound

from uber.config import c
from uber.custom_tags import readable_join
from uber.decorators import all_renderable, ajax, ajax_gettable, requires_account, render
from uber.errors import HTTPRedirect
from uber.forms import load_forms
import sqlalchemy as sa
from sqlalchemy import func
from uber.models import Attendee, LotteryApplication, RoomAssignment
from uber.models.hotel import (HotelRoomInventory, InventoryPartitionBlock,
                               RoomAssignmentInvite, WaitlistRevealLink,
                               room_assignment_occupant)
from uber.email import EmailService
from uber.utils import RegistrationCode, validate_model, get_age_from_birthday, normalize_email_legacy

log = logging.getLogger(__name__)



def _room_url(assignment_id, attendee_id='', message=''):
    """Build the per-room editor URL (`room?id=...&attendee_id=...`)
    with all components individually URL-quoted.

    Built directly here because `HTTPRedirect` quotes each `{}`
    substitution as a whole; if we tried to pass a pre-built
    `id=X&attendee_id=Y` as one substitution it would emit
    `id%3DX%26attendee_id%3DY` and CherryPy would parse a single
    garbled query param. So instead we return the fully-formatted
    URL and call `raise HTTPRedirect(_room_url(...))` with no
    further substitution.
    """
    from urllib.parse import quote
    qs = 'id={}'.format(quote(str(assignment_id)))
    if attendee_id:
        qs += '&attendee_id={}'.format(quote(str(attendee_id)))
    if message:
        qs += '&message={}'.format(quote(str(message)))
    return 'room?' + qs


def _require_unlocked(ra, attendee_id=''):
    """Raise HTTPRedirect back to the room editor if the assignment has
    been exported to the hotel. Once `ra.export_locked` is True the
    booking has been transferred and nothing changes locally any more.
    """
    if ra.export_locked:
        raise HTTPRedirect(_room_url(
            ra.id, attendee_id,
            message='This booking has been transferred to the hotel '
                    'and can no longer be edited from here.'))


def _open_seats(session, ra):
    """How many more people can be added to this room (occupants +
    pending invites combined). Capacity comes from the inventory."""
    cap = ra.inventory.capacity if ra.inventory else 0
    occupant_count = len(getattr(ra, 'occupants', None) or [])
    pending = (session.query(RoomAssignmentInvite)
               .filter_by(room_assignment_id=ra.id).count())
    return max(0, cap - occupant_count - pending)


def _generate_invite_token():
    """Short URL-safe code (~10 chars). Doubles as the redeem code
    shown to the leader for out-of-band sharing."""
    return secrets.token_urlsafe(8)[:12]


def _effective_vault_reference(ra):
    """The vault scope a card for this room belongs to. Mirrors the
    logic in `create_vault_session`: prefer the inventory's explicit
    `vault_reference`, else a per-hotel fallback, else 'default'.

    A vaulted card token is only valid within its own reference, so two
    rooms can share a card iff their effective references match (e.g. a
    suite and its connectors at the same hotel)."""
    inv = ra.inventory
    if inv and inv.vault_reference:
        return inv.vault_reference
    if inv:
        return f"hotel_{inv.hotel_id}"
    return "default"


def _render_room_detail(session, assignment_id, attendee_id, message):
    """Per-room editor context. Module-level so the @all_renderable
    machinery doesn't wrap it as a renderable handler (which would
    have CherryPy looking for `hotel_lottery/_render_room_detail.html`).
    """
    ra = session.query(RoomAssignment).get(assignment_id)
    if not ra:
        raise HTTPRedirect('rooms?message={}', 'Room not found.')

    # Resolve the viewer's attendee - explicit attendee_id wins (admin
    # support flows can pass one), otherwise fall back to whichever
    # attendee is logged in.
    viewer = None
    if attendee_id:
        # Cross-attendee viewing requires Hotel Lottery Admin OR the
        # attendee belonging to the logged-in attendee account.
        _require_view_as_attendee(session, attendee_id)
        viewer = session.attendee(attendee_id)
    else:
        viewer = _viewer_attendee(session)
    if not viewer:
        # `/preregistration/homepage` crashes if the requester is
        # logged in as an admin with no AttendeeAccount, so route
        # the dead-end to the landing page instead.
        raise HTTPRedirect('/landing/index?message={}',
                           'Please log in as an attendee to view this room.')

    is_leader = (viewer.id == ra.attendee_id)
    is_occupant = any(o.id == viewer.id for o in (ra.occupants or []))
    if not is_leader and not is_occupant:
        raise HTTPRedirect('rooms?message={}',
                           'You do not have access to that room.')

    # Pending invites + capacity. Leader-only data; guests see only
    # the room itself.
    pending_invites = []
    open_seats = 0
    if is_leader:
        pending_invites = (session.query(RoomAssignmentInvite)
                           .filter_by(room_assignment_id=ra.id)
                           .order_by(RoomAssignmentInvite.created.asc()).all())
        open_seats = _open_seats(session, ra)

    # Cross-room copy candidates: every distinct occupant across the
    # leader's OTHER rooms (excludes this one and the leader themselves).
    # Also collect the leader's OTHER rooms once so we can reuse the
    # query for the card-reuse picker below.
    copy_candidates = []
    card_source_rooms = []
    if is_leader:
        other_rooms = (session.query(RoomAssignment)
                       .filter(RoomAssignment.attendee_id == viewer.id,
                               RoomAssignment.id != ra.id,
                               RoomAssignment.status.in_(
                                   [c.ASSIGNED, c.SECURED])).all())
        seen_ids = {o.id for o in (ra.occupants or [])}
        for other in other_rooms:
            for occ in (other.occupants or []):
                if occ.id in seen_ids or occ.id == viewer.id:
                    continue
                seen_ids.add(occ.id)
                copy_candidates.append(occ)

        # Card-reuse candidates: the leader's other rooms that already
        # have a card on file AND share this room's vault scope (so the
        # token is actually valid here - see `_effective_vault_reference`).
        # Only offered when this room still needs a card and isn't locked.
        if ra.require_cc and not ra.export_locked:
            target_ref = _effective_vault_reference(ra)
            for other in other_rooms:
                if not other.cc_token:
                    continue
                if _effective_vault_reference(other) != target_ref:
                    continue
                card_source_rooms.append(other)

    return {
        'assignment': ra,
        'viewer': viewer,
        'is_leader': is_leader,
        'application': ra.lottery_application,
        'pending_invites': pending_invites,
        'open_seats': open_seats,
        'copy_candidates': copy_candidates,
        'card_source_rooms': card_source_rooms,
        'message': message,
        'vault_enabled': c.VAULT_ENABLED,
    }


def _viewer_attendee(session):
    """Resolve the currently-logged-in viewer to their Attendee record.

    Tries the attendee-account session key first (the normal
    attendee-facing login); falls back to the admin `account_id`'s
    linked attendee so support admins can view attendee pages too.
    Returns None if nothing matches.
    """
    from uber.models import AttendeeAccount
    aa_id = (cherrypy.session.get('attendee_account_id')
             if cherrypy.session else None)
    if aa_id:
        aa = session.query(AttendeeAccount).get(aa_id)
        if aa and aa.attendees:
            return aa.attendees[0]
    # Admin fallback - for support flows where a lottery admin opens
    # an attendee's page directly.
    admin_id = (cherrypy.session.get('account_id')
                if cherrypy.session else None)
    if admin_id:
        from uber.models import AdminAccount
        admin = session.query(AdminAccount).get(admin_id)
        if admin and admin.attendee:
            return admin.attendee
    return None


def _attendee_account_owns(session, attendee_id):
    """True iff the currently-logged-in attendee account claims the
    given attendee_id among its attendees. Used as the non-admin
    branch of the view-as-attendee access gate."""
    if not attendee_id:
        return False
    from uber.models import AttendeeAccount
    aa_id = (cherrypy.session.get('attendee_account_id')
             if cherrypy.session else None)
    if not aa_id:
        return False
    aa = session.query(AttendeeAccount).get(aa_id)
    if not aa:
        return False
    return any(str(a.id) == str(attendee_id) for a in (aa.attendees or []))


def _can_view_as_attendee(session, attendee_id):
    """Authorization for the attendee-facing hotel pages when an
    explicit `?attendee_id=X` is supplied.

    Two paths are permitted:
      1. The requester is a global Hotel Lottery Admin (lottery
         support staff viewing/editing any attendee's records).
      2. The requester is logged into the AttendeeAccount that owns
         the target attendee (the normal multi-attendee household
         case - one account, multiple attendees).

    Anything else - including admins without hotel_lottery_admin
    access, or attendees trying to pry at someone else's URL - is
    rejected. The lottery admin path is the *only* mechanism by
    which one human can view a different human's hotel pages, and
    by design that's the same population that already sees the
    "View as Attendee" button in /hotel_lottery_admin/.
    """
    from uber.lottery_perms import is_lottery_admin
    if is_lottery_admin():
        return True
    return _attendee_account_owns(session, attendee_id)


def _require_view_as_attendee(session, attendee_id, redirect='rooms'):
    """Hard gate: raise HTTPRedirect to landing if the requester isn't
    allowed to view the given attendee. Use at the top of every
    attendee-facing handler that accepts an explicit attendee_id."""
    if _can_view_as_attendee(session, attendee_id):
        return
    raise HTTPRedirect(
        '/landing/index?message={}',
        'You do not have permission to view that attendee.')


def _join_room_group(session, application, group_id):
    message, got_new_conf_num = '', None

    try:
        room_group = session.lottery_application(group_id)
    except NoResultFound:
        message = f"No {c.HOTEL_LOTTERY_GROUP_TERM.lower()} found!"
    else:
        if len(room_group.valid_group_members) == 3:
            message = f"This {c.HOTEL_LOTTERY_GROUP_TERM.lower()} is full."
        elif room_group.is_staff_entry and not application.qualifies_for_staff_lottery:
            message = f"You are not eligible to join this {c.HOTEL_LOTTERY_GROUP_TERM.lower()}."
        elif room_group.locked:
            message = f"This {c.HOTEL_LOTTERY_GROUP_TERM.lower()} is locked."
    if message:
        return message, got_new_conf_num
    
    if application.entry_type != c.GROUP_ENTRY and application.status != c.COMPLETE:
        # We can revert to a completed app if the attendee leaves the group,
        # but it's too messy for incomplete apps, so we clear them instead
        defaults = LotteryApplication().to_dict()
        for attr in defaults:
            if attr not in ['id', 'attendee_id', 'response_id',
                            'cellphone',
                            'terms_accepted', 'data_policy_accepted',
                            'entry_started', 'entry_metadata']:
                setattr(application, attr, defaults.get(attr))
    elif application.entry_type != c.GROUP_ENTRY:
        application.confirmation_num = ''
        got_new_conf_num = True

    if not application.entry_started:
        application.entry_started = datetime.now()
        application.entry_metadata = {
            'ip_address': cherrypy.request.headers.get('X-Forwarded-For', cherrypy.request.remote.ip),
            'user_agent': cherrypy.request.headers.get('User-Agent', ''),
            'referer': cherrypy.request.headers.get('Referer', '')}

    application.status = c.COMPLETE
    application.entry_type = c.GROUP_ENTRY
    application.last_submitted = datetime.now()
    application.attendee.hotel_eligible = False
    application.parent_application = room_group
    if application.is_staff_entry and not application.parent_application.is_staff_entry:
        application.is_staff_entry = False
    elif application.parent_application.is_staff_entry:
        application.is_staff_entry = True

    return message, got_new_conf_num


def _is_post_cutoff(application):
    """True when this entry is being accepted past the standard lottery
    form deadline - i.e. the global form window is closed but a
    LotteryRun with apply_cutoff=False is still letting entries through.

    Drives the post-cutoff banner in the confirmation email.
    """
    if application.is_staff_entry:
        return not c.STAFF_HOTEL_LOTTERY_OPEN
    if application.qualifies_for_staff_lottery:
        return not c.STAFF_HOTEL_LOTTERY_OPEN and not c.HOTEL_LOTTERY_OPEN
    return not c.HOTEL_LOTTERY_OPEN


def _max_room_capacity_for_group(session, application):
    """Largest awarded-room capacity minus the leader, with a sensible
    fallback. Used to cap group invites - the leader can rotate
    occupants per-room via the M2M, but the group size is bounded by
    the largest room they've actually been awarded.
    """
    capacities = [
        (ra.inventory.capacity if ra.inventory else 0)
        for ra in (session.query(RoomAssignment)
                   .filter(RoomAssignment.lottery_application_id == application.id,
                           RoomAssignment.status.in_([c.ASSIGNED, c.SECURED]))
                   .all())
    ]
    if not capacities:
        return 3
    return max(0, max(capacities) - 1)


def _disband_room_group(session, application):
    old_room_group_name = application.room_group_name
    application.room_group_name = ''
    application.invite_code = ''

    for member in application.group_members:
        member = _reset_group_member(member)
        session.add(member)
        session.commit()
        EmailService.queue_email(
            session, 'hotel_lottery_group_removed', member,
            subject=f'{c.EVENT_NAME} Lottery {c.HOTEL_LOTTERY_GROUP_TERM} "{old_room_group_name}" Disbanded',
            data={
            'app': member, 'parent': application, 'old_room_group_name': old_room_group_name})
    
    session.commit()


def _reset_group_member(application):
    if application.guarantee_policy_accepted and not application.finalized:
        if application.suite_type_preference:
            application.entry_type = c.SUITE_ENTRY
        else:
            application.entry_type = c.ROOM_ENTRY
        application.last_submitted = datetime.now()
    else:
        application.entry_type = None
        application.status = c.WITHDRAWN
        application.terms_accepted = False
        application.data_policy_accepted = False
        application.attendee.hotel_eligible = True
    
    if application.status == c.COMPLETE and c.STAFF_HOTEL_LOTTERY_OPEN and application.qualifies_for_staff_lottery:
        application.is_staff_entry = True
    else:
        application.is_staff_entry = False

    application.parent_application = None
    application.confirmation_num = ''
    return application


def _clear_application(application, status=c.WITHDRAWN):
    application.attendee.hotel_eligible = True
    keep_attrs = [
        'id', 'attendee_id', 'response_id', 'cellphone']

    defaults = LotteryApplication().to_dict()
    for attr in defaults:
        if attr not in keep_attrs:
            setattr(application, attr, defaults.get(attr))
    application.status = status
    return application


def _return_link(attendee_id):
    if c.ATTENDEE_ACCOUNTS_ENABLED:
        return "../preregistration/homepage?"
    else:
        return f"../preregistration/confirm?id={attendee_id}&"


@all_renderable(public=True)
class Root:
    @ajax_gettable
    def waitlist_reveal(self, session, token=None, **params):
        """Public page (token-gated). Pre-reveal: countdown. Post-reveal:
        renders the external URL. The page polls itself near the reveal
        time so attendees don't need to refresh manually.
        """
        return self._waitlist_reveal_payload(session, token)

    def _waitlist_reveal_payload(self, session, token):
        if not token:
            return {'error': 'missing-token'}
        link = session.query(WaitlistRevealLink).filter_by(token=token).first()
        if not link:
            return {'error': 'invalid-token'}
        reveal = link.waitlist_reveal
        if not reveal or not reveal.active:
            return {'error': 'inactive'}

        if not link.clicked_at:
            link.clicked_at = datetime.now()
            session.add(link)
            session.commit()

        now = datetime.now(c.EVENT_TIMEZONE) if reveal.reveal_at else None
        is_revealed = reveal.reveal_at and reveal.reveal_at <= now
        return {
            'reveal_name': reveal.name,
            'reveal_at_iso': reveal.reveal_at.isoformat() if reveal.reveal_at else None,
            'is_revealed': bool(is_revealed),
            'external_url': reveal.external_url if is_revealed else None,
        }

    # Plain HTML view (the email links point here; the JS-poll variant uses
    # the ajax endpoint above when polling for reveal time).
    def waitlist_reveal_page(self, session, token=None, message=''):
        if not token:
            raise HTTPRedirect('../preregistration/homepage')
        link = session.query(WaitlistRevealLink).filter_by(token=token).first()
        if not link or not link.waitlist_reveal or not link.waitlist_reveal.active:
            return {'error': 'invalid-token', 'message': message}

        reveal = link.waitlist_reveal
        if not link.clicked_at:
            link.clicked_at = datetime.now()
            session.add(link)
            session.commit()

        now = datetime.now(c.EVENT_TIMEZONE) if reveal.reveal_at else None
        return {
            'reveal': reveal,
            'token': token,
            'is_revealed': bool(reveal.reveal_at and reveal.reveal_at <= now),
            'message': message,
        }

    @requires_account(LotteryApplication)
    def confirm_interest(self, session, id, csrf_token=None):
        """Stamp last_confirmed_at on a LotteryApplication.

        Visible from the status page when the admin set
        confirmation_requested_at and the attendee hasn't confirmed since.
        LotteryRun.confirmation_window_start filters which apps are
        eligible for the next run based on this timestamp.
        """
        from uber.utils import check_csrf
        if cherrypy.request.method != 'POST':
            raise HTTPRedirect('index?id={}', id)
        check_csrf(csrf_token)
        application = session.lottery_application(id)
        application.last_confirmed_at = datetime.now()
        session.add(application)
        session.commit()
        raise HTTPRedirect(
            'index?id={}&message={}', id,
            "Thanks - your interest in the hotel lottery has been confirmed.")

    @requires_account(Attendee)
    def copy_booking_info(self, session, attendee_id, target_id, source_id,
                          return_to_room='', csrf_token=None):
        """Copy CC vault token + billing address from one of the attendee's
        assignments to another. Both must belong to the same attendee.

        When `return_to_room` is truthy the redirect lands back on the
        target room's editor (the per-room "Card on file" surface posts
        with it set); otherwise it falls back to the rooms list.
        """
        from uber.utils import check_csrf
        if cherrypy.request.method != 'POST':
            raise HTTPRedirect('rooms?attendee_id={}', attendee_id)
        check_csrf(csrf_token)

        def _fail(msg):
            if return_to_room and target_id:
                raise HTTPRedirect(_room_url(target_id, attendee_id, message=msg))
            raise HTTPRedirect('rooms?attendee_id={}&message={}', attendee_id, msg)

        attendee = session.attendee(attendee_id)
        source = session.query(RoomAssignment).get(source_id)
        target = session.query(RoomAssignment).get(target_id)
        if not source or not target or source.attendee_id != attendee.id \
                or target.attendee_id != attendee.id:
            _fail('Assignment not found.')

        if target.export_locked:
            _fail('This booking has been transferred to the hotel and the '
                  'card on file cannot be changed here.')
        if not source.cc_token:
            _fail('That room has no card on file to reuse.')
        # A vaulted token is only valid within its own vault scope, so
        # refuse a cross-hotel copy that would land an unusable token.
        if _effective_vault_reference(source) != _effective_vault_reference(target):
            _fail("That room's card can't be reused here - it belongs to a "
                  "different hotel's payment system.")

        copy_fields = [
            'cc_token', 'cc_last_four', 'cc_card_type', 'cc_card_holder',
            'cc_card_expiry', 'cc_issuer_brand', 'cc_issuer_bank',
            'cc_issuer_country', 'cc_issuer_card_type', 'cc_issuer_card_level',
            'cc_captured_at',
            'address1', 'address2', 'city', 'region', 'zip_code', 'country',
            'hotel_rewards_number',
        ]
        for f in copy_fields:
            setattr(target, f, getattr(source, f))
        if target.status == c.ASSIGNED and target.cc_token and target.require_cc:
            target.status = c.SECURED
        session.add(target)
        session.commit()

        msg = 'Card reused from your other room.'
        if return_to_room:
            raise HTTPRedirect(_room_url(target.id, attendee_id, message=msg))
        raise HTTPRedirect('rooms?attendee_id={}&message={}', attendee_id, msg)

    @requires_account(Attendee)
    def room(self, session, id, attendee_id=None, message='', **params):
        """Per-room editor at /hotel_lottery/room?id=X.

        Served from a query-string URL rather than a positional path
        component so the relative asset paths in base.html (which assume
        depth 1 from the host) keep resolving.
        """
        return _render_room_detail(session, id, attendee_id, message)

    @requires_account(Attendee)
    def rooms(self, session, attendee_id=None, message='', **params):
        # List view. Fall back to whichever attendee is logged in.
        if not attendee_id:
            viewer = _viewer_attendee(session)
            if viewer:
                attendee_id = viewer.id
        if not attendee_id:
            raise HTTPRedirect('../preregistration/homepage')

        # Cross-attendee viewing (an admin passing ?attendee_id=X for
        # someone other than themselves) requires Hotel Lottery Admin
        # access, or the attendee belonging to the logged-in account.
        _require_view_as_attendee(session, attendee_id)

        attendee = session.attendee(attendee_id)
        assignments = (session.query(RoomAssignment)
                       .filter_by(attendee_id=attendee.id)
                       .order_by(RoomAssignment.assigned_check_in_date
                                 .asc().nullsfirst(),
                                 RoomAssignment.created.asc()).all())

        # Also include rooms where this attendee is an occupant but
        # not the booker (so guests see the rooms they're part of).
        guest_in = (session.query(RoomAssignment)
                    .join(room_assignment_occupant,
                          room_assignment_occupant.c.room_assignment_id == RoomAssignment.id)
                    .filter(room_assignment_occupant.c.attendee_id == attendee.id)
                    .filter(RoomAssignment.attendee_id != attendee.id).all())

        primaries = [ra for ra in assignments if not ra.parent_assignment_id]
        children_by_parent = {}
        for ra in assignments:
            if ra.parent_assignment_id:
                children_by_parent.setdefault(
                    ra.parent_assignment_id, []).append(ra)
        primary_ids = {p.id for p in primaries}
        for p in primaries:
            p.children = children_by_parent.get(p.id, [])
            p.orphan = False
        for ra in assignments:
            if ra.parent_assignment_id and ra.parent_assignment_id not in primary_ids:
                ra.children = []
                ra.orphan = True
                primaries.append(ra)

        return {
            'attendee': attendee,
            'primaries': primaries,
            'guest_in': guest_in,
            'message': message,
        }

    # NB: `_render_room_detail` lives as a module-level function below.
    # If it were a Root method, `@all_renderable()` would wrap it like
    # any other handler and CherryPy would look for a template named
    # `hotel_lottery/_render_room_detail.html`.


    @requires_account(Attendee)
    def invite_email(self, session, assignment_id, attendee_id='',
                     email='', csrf_token=None):
        from uber.utils import check_csrf
        if cherrypy.request.method != 'POST':
            raise HTTPRedirect(_room_url(assignment_id, attendee_id))
        check_csrf(csrf_token)
        ra = session.query(RoomAssignment).get(assignment_id)
        if not ra:
            raise HTTPRedirect('rooms?message={}', 'Room not found.')
        _require_unlocked(ra, attendee_id)

        if _open_seats(session, ra) <= 0:
            raise HTTPRedirect(_room_url(
                assignment_id, attendee_id,
                message='Room is at capacity.'))
        email = (email or '').strip()
        if not email:
            raise HTTPRedirect(_room_url(
                assignment_id, attendee_id,
                message='Please enter an email address.'))

        token = _generate_invite_token()
        invite = RoomAssignmentInvite(
            room_assignment_id=ra.id,
            invite_token=token,
            email=email,
        )
        session.add(invite)
        session.commit()

        try:
            EmailService.queue_email(
                session, 'room_occupant_invite', invite,
                subject=f"{ra.attendee.full_name if ra.attendee else 'A {c.EVENT_NAME} attendee'} "
                f"invited you to share a room at {c.EVENT_NAME}",
                data={
                'invite': invite,
                'assignment': ra,
                'leader': ra.attendee,
                'token': token,
            })
        except Exception:
            # Bad email or template missing - surface a soft message
            # but keep the invite row so the leader can still hand the
            # code over directly.
            log.exception("Failed to send room invite email")

        raise HTTPRedirect(_room_url(
            assignment_id, attendee_id,
            message=f'Invite sent to {email}.'))

    @requires_account(Attendee)
    def invite_code(self, session, assignment_id, attendee_id='',
                    csrf_token=None):
        from uber.utils import check_csrf
        if cherrypy.request.method != 'POST':
            raise HTTPRedirect(_room_url(assignment_id, attendee_id))
        check_csrf(csrf_token)
        ra = session.query(RoomAssignment).get(assignment_id)
        if not ra:
            raise HTTPRedirect('rooms?message={}', 'Room not found.')
        _require_unlocked(ra, attendee_id)

        if _open_seats(session, ra) <= 0:
            raise HTTPRedirect(_room_url(
                assignment_id, attendee_id,
                message='Room is at capacity.'))

        token = _generate_invite_token()
        invite = RoomAssignmentInvite(
            room_assignment_id=ra.id,
            invite_token=token,
        )
        session.add(invite)
        session.commit()
        # Surface the code via the standard message-alert flow so the
        # editor's chrome doesn't sprout an extra inline alert.
        raise HTTPRedirect(_room_url(
            assignment_id, attendee_id,
            message=f"New invite code generated: {token}. Share it with "
                    "one friend; they enter it on their own Hotel Rooms "
                    "page."))

    @requires_account(Attendee)
    def cancel_room_invite(self, session, invite_id, attendee_id='',
                           csrf_token=None):
        """Leader-side cancel of a pending RoomAssignmentInvite.

        Named distinctly from the existing application-level lottery-group
        `cancel_invite` handler below so the two routes don't shadow each
        other (Python keeps the last class-body definition; without the
        rename, this method would silently lose to the LotteryApplication
        one and POSTs from the room editor would 500 with a TypeError on
        the wrong-shape arg list).
        """
        from uber.utils import check_csrf
        if cherrypy.request.method != 'POST':
            raise HTTPRedirect('rooms')
        check_csrf(csrf_token)
        invite = session.query(RoomAssignmentInvite).get(invite_id)
        if not invite:
            raise HTTPRedirect('rooms')
        assignment_id = invite.room_assignment_id
        session.delete(invite)
        session.commit()
        raise HTTPRedirect(_room_url(
            assignment_id, attendee_id,
            message='Invite cancelled.'))

    @requires_account(Attendee)
    def invite(self, session, token='', action='', attendee_id='',
               csrf_token=None):
        """Accept / reject landing page for a room invite token. A miss
        renders the same 'expired' template regardless of the actual
        reason (cancelled, redeemed, never existed) to avoid leaking
        whether a given token was ever real.

        When `attendee_id` is supplied (the view-as-attendee flow - an
        admin or a household account acting for one of its attendees),
        that attendee is the one who joins the room, not whoever's
        cookie is logged in. The id is gated by `_require_view_as_attendee`
        so it can't be used to add an arbitrary attendee.
        """
        invite = (session.query(RoomAssignmentInvite)
                  .filter_by(invite_token=(token or '').strip()).first()) if token else None

        if cherrypy.request.method == 'POST' and invite and action:
            from uber.utils import check_csrf
            check_csrf(csrf_token)

            # Resolve the accepting attendee. An explicit attendee_id
            # (view-as flow) wins, gated by the same access check the
            # rest of the rooms surface uses; otherwise fall back to
            # whoever's logged in.
            if attendee_id:
                _require_view_as_attendee(session, attendee_id)
                acceptor = session.attendee(attendee_id)
            else:
                acceptor = _viewer_attendee(session)
            if not acceptor:
                raise HTTPRedirect('/landing/index?message={}',
                                   'Please log in as an attendee to accept this invite.')

            ra = invite.room_assignment
            assignment_id = ra.id
            session.delete(invite)
            if action == 'accept' and ra and acceptor.id != ra.attendee_id:
                # Avoid duplicate occupant rows.
                if not any(o.id == acceptor.id for o in (ra.occupants or [])):
                    ra.occupants.append(acceptor)
                    session.add(ra)
            session.commit()
            if action == 'accept':
                raise HTTPRedirect(_room_url(
                    assignment_id, attendee_id or acceptor.id,
                    message='You have joined the room.'))
            raise HTTPRedirect(
                'rooms?attendee_id={}&message={}',
                attendee_id or acceptor.id, 'Invite declined.')

        return {
            'invite': invite,
            'assignment': invite.room_assignment if invite else None,
            'leader': invite.room_assignment.attendee if invite else None,
            'attendee_id': attendee_id,
        }

    @requires_account(Attendee)
    def redeem_code(self, session, code='', attendee_id='', csrf_token=None):
        from uber.utils import check_csrf
        if cherrypy.request.method != 'POST':
            raise HTTPRedirect('rooms')
        check_csrf(csrf_token)
        code = (code or '').strip()
        invite = (session.query(RoomAssignmentInvite)
                  .filter_by(invite_token=code).first()) if code else None
        if not invite:
            if attendee_id:
                raise HTTPRedirect(
                    'rooms?attendee_id={}&message={}', attendee_id,
                    'That invite has expired or been cancelled.')
            raise HTTPRedirect(
                'rooms?message={}',
                'That invite has expired or been cancelled.')
        # Carry the view-as attendee_id onto the invite landing page so
        # the accept posts on behalf of the right attendee.
        if attendee_id:
            raise HTTPRedirect('invite?token={}&attendee_id={}', code, attendee_id)
        raise HTTPRedirect('invite?token={}', code)

    @requires_account(Attendee)
    def remove_occupant(self, session, assignment_id, occupant_attendee_id,
                        attendee_id='', csrf_token=None):
        from uber.utils import check_csrf
        if cherrypy.request.method != 'POST':
            raise HTTPRedirect(_room_url(assignment_id, attendee_id))
        check_csrf(csrf_token)
        ra = session.query(RoomAssignment).get(assignment_id)
        if not ra:
            raise HTTPRedirect('rooms?message={}', 'Room not found.')
        _require_unlocked(ra, attendee_id)

        if occupant_attendee_id == ra.attendee_id:
            raise HTTPRedirect(_room_url(
                assignment_id, attendee_id,
                message='The room booker cannot be removed.'))

        target = session.attendee(occupant_attendee_id)
        if target and target in (ra.occupants or []):
            ra.occupants.remove(target)
            session.add(ra)
            session.commit()
        raise HTTPRedirect(_room_url(
            assignment_id, attendee_id,
            message='Occupant removed.'))

    @requires_account(Attendee)
    def leave_room(self, session, assignment_id, attendee_id='',
                   csrf_token=None):
        from uber.utils import check_csrf
        if cherrypy.request.method != 'POST':
            raise HTTPRedirect(_room_url(assignment_id, attendee_id))
        check_csrf(csrf_token)
        ra = session.query(RoomAssignment).get(assignment_id)
        if not ra:
            raise HTTPRedirect('rooms?message={}', 'Room not found.')
        _require_unlocked(ra, attendee_id)

        # Whoever's logged in removes themselves; refuse for the booker.
        viewer = _viewer_attendee(session)
        if not viewer:
            raise HTTPRedirect('/landing/index?message={}',
                               'Please log in as an attendee to leave a room.')
        if viewer.id == ra.attendee_id:
            raise HTTPRedirect(_room_url(
                assignment_id, attendee_id,
                message='The room booker cannot leave; use Decline instead.'))
        if viewer in (ra.occupants or []):
            ra.occupants.remove(viewer)
            session.add(ra)
            session.commit()
        raise HTTPRedirect(
            'rooms?message={}', 'You have left the room.')

    # Each section of the room editor (hotel name, rewards #, special
    # requests) submits to its own POST so the editor doesn't need a
    # single mega-form. All gate on `export_locked` first.

    @requires_account(Attendee)
    def save_hotel_name(self, session, attendee_id,
                        hotel_first_name='', hotel_last_name='',
                        return_to='rooms', csrf_token=None):
        from uber.utils import check_csrf
        if cherrypy.request.method != 'POST':
            raise HTTPRedirect(return_to or 'rooms')
        check_csrf(csrf_token)

        # Authorization for editing the attendee's hotel-legal-name:
        #   - Hotel Lottery Admins may edit any attendee on their
        #     behalf (support workflows).
        #   - Otherwise the attendee_id must belong to the logged-in
        #     attendee account - a room leader cannot edit a guest's
        #     legal name on the guest's behalf.
        from uber.lottery_perms import is_lottery_admin
        if not is_lottery_admin() and not _attendee_account_owns(
                session, attendee_id):
            raise HTTPRedirect('rooms?message={}', 'Permission denied.')

        target = session.attendee(attendee_id)
        if not target:
            raise HTTPRedirect('rooms?message={}', 'Attendee not found.')
        target.hotel_first_name = (hotel_first_name or '').strip()
        target.hotel_last_name = (hotel_last_name or '').strip()
        session.add(target)
        session.commit()

        # Build the redirect URL manually - `return_to` already contains
        # `?id=...&attendee_id=...`, and HTTPRedirect's `{}` substitution
        # would percent-encode the `?` and `&` into one garbled blob.
        from urllib.parse import quote
        base = return_to or 'rooms'
        sep = '&' if '?' in base else '?'
        raise HTTPRedirect(
            base + sep + 'message=' + quote('Hotel name updated.'))

    @requires_account(Attendee)
    def save_rewards_number(self, session, assignment_id, attendee_id='',
                            hotel_rewards_number='', csrf_token=None):
        from uber.utils import check_csrf
        if cherrypy.request.method != 'POST':
            raise HTTPRedirect(_room_url(assignment_id, attendee_id))
        check_csrf(csrf_token)
        ra = session.query(RoomAssignment).get(assignment_id)
        if not ra:
            raise HTTPRedirect('rooms?message={}', 'Room not found.')
        _require_unlocked(ra, attendee_id)
        ra.hotel_rewards_number = (hotel_rewards_number or '').strip()
        session.add(ra)
        session.commit()
        raise HTTPRedirect(_room_url(
            assignment_id, attendee_id,
            message='Rewards number updated.'))

    @requires_account(Attendee)
    def save_special_requests(self, session, assignment_id, attendee_id='',
                              special_requests='', csrf_token=None):
        from uber.utils import check_csrf
        if cherrypy.request.method != 'POST':
            raise HTTPRedirect(_room_url(assignment_id, attendee_id))
        check_csrf(csrf_token)
        ra = session.query(RoomAssignment).get(assignment_id)
        if not ra:
            raise HTTPRedirect('rooms?message={}', 'Room not found.')
        _require_unlocked(ra, attendee_id)
        ra.special_requests = (special_requests or '').strip()
        session.add(ra)
        session.commit()
        raise HTTPRedirect(_room_url(
            assignment_id, attendee_id,
            message='Special requests updated.'))

    @requires_account(Attendee)
    def save_billing_address(self, session, assignment_id, attendee_id='',
                             csrf_token=None, **params):
        """Save the billing address for the card on this room. Same
        per-room write pattern as the other section saves; the address
        is captured during the secure flow but editable here too so
        attendees can correct it without re-entering their card."""
        from uber.utils import check_csrf
        if cherrypy.request.method != 'POST':
            raise HTTPRedirect(_room_url(assignment_id, attendee_id))
        check_csrf(csrf_token)
        ra = session.query(RoomAssignment).get(assignment_id)
        if not ra:
            raise HTTPRedirect('rooms?message={}', 'Room not found.')
        _require_unlocked(ra, attendee_id)

        ra.address1 = (params.get('address1', '') or '').strip()
        ra.address2 = (params.get('address2', '') or '').strip()
        ra.city = (params.get('city', '') or '').strip()
        ra.region = (params.get('region', '') or '').strip()
        ra.zip_code = (params.get('zip_code', '') or '').strip()
        ra.country = (params.get('country', '') or '').strip()
        session.add(ra)
        session.commit()
        raise HTTPRedirect(_room_url(
            assignment_id, attendee_id,
            message='Billing address updated.'))

    @requires_account(Attendee)
    def copy_occupants(self, session, target_assignment_id, attendee_id='',
                       source_attendee_ids='', csrf_token=None):
        """Bulk-add occupants the leader already invited to a sibling
        room of theirs. No new invite is sent because they're already
        on file with one of the leader's other rooms."""
        from uber.utils import check_csrf
        if cherrypy.request.method != 'POST':
            raise HTTPRedirect(
                _room_url(target_assignment_id, attendee_id))
        check_csrf(csrf_token)
        ra = session.query(RoomAssignment).get(target_assignment_id)
        if not ra:
            raise HTTPRedirect('rooms?message={}', 'Room not found.')
        _require_unlocked(ra, attendee_id)

        ids = [i.strip() for i in (source_attendee_ids or '').split(',') if i.strip()]
        if not ids:
            raise HTTPRedirect(_room_url(
                target_assignment_id, attendee_id,
                message='Pick at least one guest to copy.'))

        # Only allow attendees who are occupants of another room booked
        # by the same leader.
        my_other_rooms = (session.query(RoomAssignment)
                          .filter(RoomAssignment.attendee_id == ra.attendee_id,
                                  RoomAssignment.id != ra.id).all())
        allowed = set()
        for other in my_other_rooms:
            for occ in (other.occupants or []):
                allowed.add(occ.id)

        existing = {o.id for o in (ra.occupants or [])}
        seats = _open_seats(session, ra)
        added = 0
        for aid in ids:
            if seats <= 0:
                break
            if aid not in allowed or aid in existing or aid == ra.attendee_id:
                continue
            a = session.attendee(aid)
            if not a:
                continue
            ra.occupants.append(a)
            existing.add(a.id)
            seats -= 1
            added += 1
        if added:
            session.add(ra)
            session.commit()
        raise HTTPRedirect(_room_url(
            target_assignment_id, attendee_id,
            message=f'Copied {added} guest(s) into this room.'))

    @requires_account(Attendee)
    def start(self, session, attendee_id, message="", **params):
        _require_view_as_attendee(session, attendee_id)
        attendee = session.attendee(attendee_id)
        if attendee.lottery_application and not attendee.lottery_application.can_reenter:
            raise HTTPRedirect('index?attendee_id={}', attendee.id)

        return {
            'attendee': attendee,
            'message': message,
            'homepage_account': session.get_attendee_account_by_attendee(attendee),
        }

    @requires_account(Attendee)
    def terms(self, session, attendee_id, message="", **params):
        _require_view_as_attendee(session, attendee_id)
        attendee = session.attendee(attendee_id)
        if attendee.lottery_application:
            application = attendee.lottery_application
            if not attendee.lottery_application.can_reenter:
                raise HTTPRedirect('index?attendee_id={}', attendee.id)
        else:
            application = LotteryApplication()
            application.attendee = attendee

        forms_list = ["LotteryInfo"]
        forms = load_forms(params, application, forms_list, read_only=application.current_lottery_closed)

        if cherrypy.request.method == 'POST':
            for form in forms.values():
                form.populate_obj(application)
            session.add(application)
            if application.can_reenter:
                application.status = c.PARTIAL
            session.commit()

            if params.get('group'):
                raise HTTPRedirect(f'room_group?id={application.id}')
            elif params.get('suite'):
                raise HTTPRedirect(f'suite_lottery?id={application.id}')
            elif params.get('room'):
                raise HTTPRedirect(f'room_lottery?id={application.id}')
            else:
                group_id = params.get('group_id')
                if application.status not in [c.PARTIAL, c.WITHDRAWN]:
                    message = "Application status has changed, please view your new options below."
                elif not group_id:
                    message = f'Group lookup failed. Please use the "Join {c.HOTEL_LOTTERY_GROUP_TERM}" button to try again.'
                else:
                    message, _ = _join_room_group(session, application, group_id)

                if not message:
                    room_group = session.lottery_application(group_id)
                    message = f'Successfully joined {c.HOTEL_LOTTERY_GROUP_TERM.lower()} "{room_group.room_group_name}"!'
                raise HTTPRedirect(f'index?id={application.id}&message={message}')

        return {
            'id': application.id,
            'attendee_id': attendee_id,
            'forms': forms,
            'message': message,
            'application': application,
            'attendee': attendee,
        }

    @requires_account([Attendee, LotteryApplication])
    def index(self, session, attendee_id=None, message="", **params):
        if 'id' in params:
            application = session.lottery_application(params['id'])
            attendee_id = application.attendee.id
        elif attendee_id:
            attendee = session.attendee(attendee_id)
            application = attendee.lottery_application
        elif c.ATTENDEE_ACCOUNTS_ENABLED:
            raise HTTPRedirect(f'../preregistration/homepage')
        else:
            raise HTTPRedirect(f'../landing/index')

        # Once we've resolved an attendee_id from either path, gate
        # cross-attendee access on Hotel Lottery Admin / same-account.
        if attendee_id:
            _require_view_as_attendee(session, attendee_id)

        if not application:
            # Attendees with no lottery application but with at least one
            # RoomAssignment (e.g. department-granted, partition grant,
            # manual) should land on their rooms page rather than the
            # lottery entry start screen. Everyone else goes to start.
            if attendee_id:
                attendee = session.attendee(attendee_id)
                if attendee.room_assignments:
                    raise HTTPRedirect(f'rooms?attendee_id={attendee_id}')
            raise HTTPRedirect(f'start?attendee_id={attendee_id}')
        elif application.locked:
            pass
        elif not application.terms_accepted:
            raise HTTPRedirect(f'terms?attendee_id={attendee_id}')
        elif application.entry_form_completed and not application.guarantee_policy_accepted:
            raise HTTPRedirect(f'guarantee_confirm?id={application.id}')

        forms_list = ["RoomLottery", "SuiteLottery"]
        if application.parent_application:
            forms = load_forms(params, application.parent_application, forms_list, read_only=True)
        else:
            forms = load_forms(params, application, forms_list, read_only=True)

        contact_form_dict = load_forms(params, application, ["LotteryInfo"],
                                       read_only=application.locked)

        return {
            'id': application.id,
            'attendee_id': attendee_id,
            'homepage_account': session.get_attendee_account_by_attendee(application.attendee),
            'forms': forms,
            'lottery_info': contact_form_dict['lottery_info'],
            'message': message,
            'confirm': params.get('confirm', ''),
            'action': params.get('action', ''),
            'application': application
        }
    
    @requires_account(LotteryApplication)
    def update_contact_info(self, session, id, **params):
        application = session.lottery_application(id)
        if application.locked:
            raise HTTPRedirect('index?id={}&message={}', application.id,
                               "You cannot edit your contact info at this time.")

        forms = load_forms(params, application, ["LotteryInfo"])
        for form in forms.values():
            form.populate_obj(application)
        raise HTTPRedirect('index?id={}&message={}',
                           application.id,
                           "Contact information updated!")

    @requires_account(LotteryApplication)
    def enter_attendee_lottery(self, session, id=None, **params):
        application = session.lottery_application(id)
        application.is_staff_entry = False
        application.last_submitted = datetime.now()
        application.status = c.COMPLETE
        application.confirmation_num = ''
        application.attendee.hotel_eligible = False
        session.add(application)
        
        EmailService.queue_email(
            session, 'hotel_lottery_confirmation', application,
            subject=c.EVENT_NAME_AND_YEAR + f' {application.entry_type_label} Lottery Confirmation',
            data={
            'app': application,
            'maybe_swapped': False,
            'new_conf': False,
            'post_cutoff': _is_post_cutoff(application),
            'action_str': f"entering the {application.entry_type_label.lower()} attendee lottery"})

        raise HTTPRedirect('index?id={}&message={}',
                           application.id,
                           "Your staff lottery entry has been entered into the attendee lottery.")

    @requires_account(LotteryApplication)
    def reenter_lottery(self, session, id=None, **params):
        application = session.lottery_application(id)
        application = _reset_group_member(application)
        session.add(application)
        if application.status == c.COMPLETE:
            EmailService.queue_email(
                session, 'hotel_lottery_confirmation', application,
                subject=c.EVENT_NAME_AND_YEAR + f' {application.entry_type_label} Lottery Confirmation',
                data={
                'app': application,
                'maybe_swapped': False,
                'new_conf': False,
                'post_cutoff': _is_post_cutoff(application),
                'action_str': f"re-entering the {application.entry_type_label.lower()} lottery"})
        else:
            raise HTTPRedirect('start?attendee_id={}&message={}',
                               application.attendee.id,
                               "Your lottery entry has been reset and you may now re-enter.")

    @requires_account(LotteryApplication)
    def withdraw_entry(self, session, id=None, **params):
        application = session.lottery_application(id)

        has_actually_entered = application.status == c.COMPLETE or application.finalized
        was_room_group = application.room_group_name
        old_room_group = application.parent_application

        if was_room_group:
            _disband_room_group(session, application)

        _clear_application(application)

        if old_room_group:
            EmailService.queue_email(
                session, 'hotel_lottery_group_member_left', old_room_group,
                subject=f'{application.attendee.first_name} has left your {c.EVENT_NAME} Lottery {c.HOTEL_LOTTERY_GROUP_TERM}',
                data={
                'app': old_room_group, 'member': application})

        if has_actually_entered:
            EmailService.queue_email(
                session, 'hotel_lottery_cancelled', application,
                subject=c.EVENT_NAME_AND_YEAR + f' Lottery Entry Cancelled',
                data={
                'app': application})

            raise HTTPRedirect('{}message={}'.format(_return_link(application.attendee.id),
                            f"You have been removed from the hotel lottery.{' Your group has been disbanded.' if was_room_group else ''}"))
        raise HTTPRedirect('{}message={}'.format(_return_link(application.attendee.id),
                            f"Your hotel lottery entry has been cancelled."))

    @requires_account(LotteryApplication)
    def room_lottery(self, session, id=None, message="", **params):
        application = session.lottery_application(id)
        forms_list = ["RoomLottery"] + (["SuiteLottery"] if application.current_lottery_closed else [])

        if application.parent_application:
            message = f"You cannot edit your {c.HOTEL_LOTTERY_GROUP_TERM.lower()}'s application."
            raise HTTPRedirect(f'index?id={application.id}&messsage={message}')
        elif application.locked:
            raise HTTPRedirect('index?id={}&message={}', application.id,
                               "You cannot edit your lottery entry at this time.")

        forms = load_forms(params, application, forms_list, read_only=application.current_lottery_closed)

        if cherrypy.request.method == 'POST':
            for form in forms.values():
                form.populate_obj(application)

            update_group_members = application.update_group_members

            if application.status == c.COMPLETE and c.STAFF_HOTEL_LOTTERY_OPEN and application.qualifies_for_staff_lottery:
                application.is_staff_entry = True
            elif not application.can_edit:
                application.is_staff_entry = False

            application.current_step = 999
            session.commit()
            session.refresh(application)

            if not application.guarantee_policy_accepted:
                raise HTTPRedirect('guarantee_confirm?id={}', application.id)
            else:
                if application.status == c.PARTIAL:
                    application.status = c.COMPLETE
                application.last_submitted = datetime.now()

                EmailService.queue_email(
                    session, 'hotel_lottery_confirmation', application,
                    subject=c.EVENT_NAME_AND_YEAR + f' Room Lottery Updated',
                    data={
                    'app': application,
                    'post_cutoff': _is_post_cutoff(application),
                    'action_str': "updating your room lottery entry"})
                if update_group_members:
                    for member in application.valid_group_members:
                        EmailService.queue_email(
                            session, 'group_lottery_updated', application,
                            subject=c.EVENT_NAME_AND_YEAR + f' Room Lottery Updated',
                            data={
                            'app': member})

                raise HTTPRedirect('index?id={}&confirm=room&action=updated',
                                   application.id)

        return {
            'id': application.id,
            'homepage_account': session.get_attendee_account_by_attendee(application.attendee),
            'forms': forms,
            'message': message,
            'application': application,
        }
    
    @requires_account(LotteryApplication)
    def suite_lottery(self, session, id=None, message="", **params):
        application = session.lottery_application(id)
        forms_list = ["SuiteLottery"]

        if application.parent_application:
            message = f"You cannot edit your {c.HOTEL_LOTTERY_GROUP_TERM.lower()}'s application."
            raise HTTPRedirect(f'index?id={application.id}&messsage={message}')
        elif application.locked:
            raise HTTPRedirect('index?id={}&message={}', application.id,
                               "You cannot edit your lottery entry at this time.")

        forms = load_forms(params, application, forms_list, read_only=application.current_lottery_closed)

        if cherrypy.request.method == 'POST':
            for form in forms.values():
                form.populate_obj(application)

            update_group_members = application.update_group_members

            if application.status == c.COMPLETE and c.STAFF_HOTEL_LOTTERY_OPEN and application.qualifies_for_staff_lottery:
                application.is_staff_entry = True
            elif not application.can_edit:
                application.is_staff_entry = False

            application.current_step = 999
            session.commit()
            session.refresh(application)

            if not application.guarantee_policy_accepted:
                raise HTTPRedirect('guarantee_confirm?id={}', application.id)
            else:
                if application.status == c.PARTIAL:
                    application.status = c.COMPLETE
                application.last_submitted = datetime.now()

                EmailService.queue_email(
                    session, 'hotel_lottery_confirmation', application,
                    subject=c.EVENT_NAME_AND_YEAR + f' Suite Lottery Updated',
                    data={
                    'app': application,
                    'post_cutoff': _is_post_cutoff(application),
                    'action_str': "updating your suite lottery entry"})
                
                if update_group_members:
                    for member in application.valid_group_members:
                        EmailService.queue_email(
                            session, 'group_lottery_updated', application,
                            subject=c.EVENT_NAME_AND_YEAR + f' Suite Lottery Updated',
                            data={
                            'app': member})

                raise HTTPRedirect('index?id={}&confirm=suite&action=updated',
                                   application.id)

        return {
            'id': application.id,
            'homepage_account': session.get_attendee_account_by_attendee(application.attendee),
            'forms': forms,
            'message': message,
            'application': application,
            'read_only': False,
        }

    @ajax
    def validate_hotel_lottery(self, session, attendee_id=None, form_list=[], **params):
        if params.get('id') in [None, '', 'None']:
            if attendee_id:
                attendee = session.attendee(attendee_id)
                application = attendee.lottery_application or LotteryApplication()
            else:
                return {"error": "There was an issue with the form. Please refresh and try again."}
        else:
            application = session.lottery_application(params.get('id'))
            attendee = application.attendee
        
        if application.locked:
            return {"error": "You cannot edit your lottery entry at this time."}

        if not form_list:
            form_list = ["LotteryInfo"]
        elif isinstance(form_list, str):
            form_list = [form_list]
        forms = load_forms(params, application, form_list)

        all_errors = validate_model(session, forms, application)
        check_date = params.get('earliest_suite_checkin_date', params.get('earliest_room_checkin_date', ''))
        if attendee.birthdate and check_date and get_age_from_birthday(attendee.birthdate,
                                                                       check_date) < 21:
            all_errors[''].append("You must be at least 21 on your preferred check-in date.")
        if all_errors:
            return {"error": all_errors}
        current_step = params.get('current_step', 0)

        if current_step:
            # This is unusual for a validation function, but we want to save at each step of the form
            for form in forms.values():
                form.populate_obj(application)

            if not application.entry_started:
                application.entry_started = datetime.now()
                application.entry_metadata = {
                    'ip_address': cherrypy.request.headers.get('X-Forwarded-For', cherrypy.request.remote.ip),
                    'user_agent': cherrypy.request.headers.get('User-Agent', ''),
                    'referer': cherrypy.request.headers.get('Referer', '')}

            session.commit()

        return {"success": True, "step_completed": params.get('current_step', 0)}

    @requires_account(LotteryApplication)
    def guarantee_confirm(self, session, id=None, message="", **params):
        application = session.lottery_application(id)
        forms_list = ["LotteryConfirm"]
        forms = load_forms(params, application, forms_list, read_only=application.current_lottery_closed)

        if application.locked:
            raise HTTPRedirect('index?id={}&message={}', application.id,
                               "You cannot edit your lottery entry at this time.")

        if cherrypy.request.method == 'POST':
            for form in forms.values():
                form.populate_obj(application)

            maybe_swapped = application.last_submitted != None
            application.last_submitted = datetime.now()
            application.status = c.COMPLETE
            application.attendee.hotel_eligible = False

            if c.STAFF_HOTEL_LOTTERY_OPEN and application.qualifies_for_staff_lottery:
                application.is_staff_entry = True

            session.commit()
            session.refresh(application)

            room_or_suite = "suite" if application.entry_type == c.SUITE_ENTRY else "room"
            EmailService.queue_email(
                session, 'hotel_lottery_confirmation', application,
                subject=c.EVENT_NAME_AND_YEAR + f' {application.entry_type_label} Lottery Confirmation',
                data={
                'app': application,
                'maybe_swapped': maybe_swapped,
                'new_conf': False,
                'post_cutoff': _is_post_cutoff(application),
                'action_str': f"entering the {application.entry_type_label.lower()} lottery"})

            raise HTTPRedirect('index?id={}&confirm={}&action=confirmation',
                               application.id,
                               room_or_suite)
        return {
                'id': application.id,
                'homepage_account': session.get_attendee_account_by_attendee(application.attendee),
                'forms': forms,
                'message': message,
                'application': application,
            }

    @requires_account(LotteryApplication)
    def switch_entry_type(self, session, id, **params):
        application = session.lottery_application(id)

        if application.entry_type not in [c.ROOM_ENTRY, c.SUITE_ENTRY]:
            raise HTTPRedirect('index?id={}&message={}', application.id,
                               f"You cannot switch from a {application.entry_type_label} to a room or suite entry.")
        elif application.locked:
            raise HTTPRedirect('index?id={}&message={}', application.id,
                               "You cannot edit your lottery entry at this time.")

        application.status = c.PARTIAL
        application.current_step = 0
        application.guarantee_policy_accepted = False

        if application.entry_type == c.ROOM_ENTRY:
            application.entry_type = c.SUITE_ENTRY
            if 'suite_ada_info' not in c.HOTEL_LOTTERY_FORM_STEPS:
                application.wants_ada = False
                application.ada_requests = ''
        elif application.entry_type == c.SUITE_ENTRY:
            application.entry_type = c.ROOM_ENTRY
            application.suite_terms_accepted = False
            application.room_opt_out = False
            application.suite_type_preference = ''
        raise HTTPRedirect('{}_lottery?id={}&message={}', 'room' if application.entry_type == c.ROOM_ENTRY else 'suite',
                           application.id,
                           "Entry type switched! Please make sure to carefully review and confirm your new entry.")
        

    @requires_account(LotteryApplication)
    def lottery_group(self, session, id=None, message='', **params):
        """URL for the application-level lottery group flow (distinct from
        per-room occupants). Delegates to `room_group`."""
        return self.room_group(session, id=id, message=message, **params)

    @requires_account(LotteryApplication)
    def room_group(self, session, id=None, message="", **params):
        application = session.lottery_application(id)

        forms_list = ["LotteryRoomGroup"]
        forms = load_forms(params, application, forms_list, read_only=application.current_lottery_closed)

        if cherrypy.request.method == 'POST':
            pass

        # Query pending outbound invites sent by this leader
        pending_invites = []
        if application.room_group_name and not application.parent_application:
            pending_invites = session.query(LotteryApplication).filter(
                LotteryApplication.invited_by_id == application.id,
                LotteryApplication.invite_status == c.INVITE_PENDING,
            ).all()

        return {
            'id': application.id,
            'homepage_account': session.get_attendee_account_by_attendee(application.attendee),
            'forms': forms,
            'message': message,
            'application': application,
            'pending_invites': pending_invites,
            'create': params.get('create'),
            'action': params.get('action', ''),
            'new_conf': True if params.get('new_conf', "False") != "False" else False,
        }
    
    @requires_account(LotteryApplication)
    def save_group(self, session, id=None, message="", **params):
        application = session.lottery_application(id)

        if application.locked:
            raise HTTPRedirect('room_group?id={}&message={}', application.id,
                               f"You cannot edit or create a {c.HOTEL_LOTTERY_GROUP_TERM.lower()} at this time.")

        forms_list = ["LotteryRoomGroup"]
        forms = load_forms(params, application, forms_list)

        if cherrypy.request.method == 'POST':
            if not application.room_group_name or not application.invite_code:
                action = "created"
                application.invite_code = RegistrationCode.generate_random_code(LotteryApplication.invite_code)
            else:
                action = "updated"
            
            for form in forms.values():
                form.populate_obj(application)
                application.last_submitted = datetime.now()
                raise HTTPRedirect('room_group?id={}&action={}', application.id, action)

    @requires_account(LotteryApplication)
    def new_invite_code(self, session, id=None, message="", **params):
        application = session.lottery_application(id)
        application.invite_code = RegistrationCode.generate_random_code(LotteryApplication.invite_code)
        raise HTTPRedirect('room_group?id={}&message={}', application.id,
                           f"New invite code generated. Your new code is {application.invite_code}.")
    
    @requires_account(LotteryApplication)
    def remove_group_member(self, session, id=None, member_id=None, message="", **params):
        application = session.lottery_application(id)
        if application.locked:
            raise HTTPRedirect('index?id={}&message={}', application.id,
                               "You cannot remove group members at this time.")

        member = session.lottery_application(member_id)
        if application.status == c.PROCESSED or application.finalized:
            member = _clear_application(member)
        else:
            member = _reset_group_member(member)
        session.commit()
        session.refresh(member)
        EmailService.queue_email(
            session, 'hotel_lottery_group_removed', member,
            subject=f'Removed From {c.EVENT_NAME} Lottery {c.HOTEL_LOTTERY_GROUP_TERM} "{application.room_group_name}"',
            data={
            'app': member, 'parent': application, 'group_disbanded': False})
        raise HTTPRedirect('room_group?id={}&message={}', application.id,
                           f"{member.attendee.full_name} has been removed from your {c.HOTEL_LOTTERY_GROUP_TERM.lower()}.")

    @requires_account(LotteryApplication)
    def transfer_leadership(self, session, id=None, member_id=None, message="", **params):
        application = session.lottery_application(id)
        new_leader = session.lottery_application(member_id)

        if new_leader not in application.valid_group_members:
            raise HTTPRedirect('index?attendee_id={}&message={}', application.attendee.id,
                               f"{new_leader.attendee.full_name} is not a member of your {c.HOTEL_LOTTERY_GROUP_TERM.lower()}")
        elif application.locked:
            raise HTTPRedirect('index?id={}&message={}', application.id,
                               "You cannot transfer group leadership at this time.")

        leader_entry = application.to_dict()
        defaults = LotteryApplication().to_dict()

        # Room state is not copied here: it lives on `RoomAssignment` rows,
        # which already carry `lottery_application_id` pointing at the
        # leader's application.
        for attr in ['earliest_checkin_date', 'latest_checkin_date', 'earliest_checkout_date', 'latest_checkout_date',
                     'hotel_preference', 'room_type_preference', 'wants_ada', 'ada_requests',
                     'room_opt_out', 'suite_type_preference', 'suite_terms_accepted', 'guarantee_policy_accepted',
                     'room_group_name',
                     'status', 'entry_type', 'current_step']:
            setattr(new_leader, attr, leader_entry.get(attr))
            setattr(application, attr, defaults.get(attr))

        all_group_members = application.group_members + [application]
        for member in all_group_members:
            if member != new_leader:
                member.parent_application_id = new_leader.id
                session.add(member)

        application.status = new_leader.status
        application.entry_type = c.GROUP_ENTRY
        new_leader.parent_application_id = None
        session.commit()

        for member in all_group_members:
            EmailService.queue_email(
                session, 'group_lottery_leader_changed', member,
                subject=f'{c.EVENT_NAME} Lottery {c.HOTEL_LOTTERY_GROUP_TERM} Leader Changed',
                data={
                    'app': member, 'old_leader': application, 'new_leader': new_leader})
        
        raise HTTPRedirect('index?id={}&message={}', application.id,
                           f"Group leadership successfully transferred to {new_leader.attendee.full_name}.")


    @requires_account(LotteryApplication)
    def delete_group(self, session, id=None, message="", **params):
        application = session.lottery_application(id)
        if application.locked:
            raise HTTPRedirect('index?id={}&message={}', application.id,
                               f"You cannot disband your {c.HOTEL_LOTTERY_GROUP_TERM.lower()} at this time.")

        old_room_group_name = application.room_group_name
        _disband_room_group(session, application)

        application.confirmation_num = ''

        raise HTTPRedirect('index?id={}&message={}', application.id,
                           f"{old_room_group_name} has been disbanded.")

    @ajax
    def room_group_search(self, session, member_id, **params):
        application = session.lottery_application(member_id)

        invite_code, leader_email = params.get('confirmation_num'), params.get('leader_email')
        errors = []
        if not invite_code:
            errors.append("a group confirmation number")
        if not leader_email:
            errors.append(f"the {c.HOTEL_LOTTERY_GROUP_TERM.lower()} leader's email address")
        if errors:
            return {'error': f"Please enter {readable_join(errors)}."}

        #room_group = session.lookup_registration_code(invite_code, LotteryApplication)
        room_group = session.query(LotteryApplication).filter(
            LotteryApplication.confirmation_num == invite_code,
            LotteryApplication.room_group_name != '').first()

        if not room_group or room_group.attendee.normalized_email != normalize_email_legacy(leader_email) or room_group.locked or \
                room_group.is_staff_entry and (not c.STAFF_HOTEL_LOTTERY_OPEN or not application.qualifies_for_staff_lottery):
            return {'error': f"No {c.HOTEL_LOTTERY_GROUP_TERM.lower()} found. Please check the confirmation number and email address, \
                    and make sure the group you're trying to join is valid, open, and not full."}

        return {
            'success': True,
            'invite_code': invite_code,
            'room_group_name': room_group.room_group_name,
            'leader_name': room_group.group_leader_name,
            'room_group_id': room_group.id
        }

    @requires_account(LotteryApplication)
    def join_group(self, session, id=None, message="", **params):
        application = session.lottery_application(id)

        if application.locked:
            raise HTTPRedirect('index?id={}&message={}', application.id,
                               f"You cannot join a {c.HOTEL_LOTTERY_GROUP_TERM.lower()} at this time.")
        got_new_conf_num = False

        if cherrypy.request.method == "POST":
            if not params.get('room_group_id'):
                message = "Group ID invalid!"
            elif application.valid_group_members or application.room_group_name:
                message = "Please disband your own group before joining another group."
            elif application.parent_application:
                message = f"You are already in a {c.HOTEL_LOTTERY_GROUP_TERM.lower()}."
            if not message:
                message, got_new_conf_num = _join_room_group(session, application, params.get('room_group_id'))
                
                if message:
                    raise HTTPRedirect('room_group?id={}&message={}', application.id, message)

                room_group = session.lottery_application(params.get('room_group_id'))
                
                session.commit()
                session.refresh(application)

                EmailService.queue_email(
                    session, 'group_lottery_member_joined', room_group,
                    subject=f'{application.attendee.first_name} has joined your {c.EVENT_NAME} Lottery {c.HOTEL_LOTTERY_GROUP_TERM}',
                    data={
                    'app': room_group, 'member': application})
                
                EmailService.queue_email(
                    session, 'hotel_lottery_confirmation', application,
                    subject=c.EVENT_NAME_AND_YEAR + f' {application.entry_type_label} Lottery Confirmation',
                    data={
                    'app': application,
                    'new_conf': got_new_conf_num,
                    'post_cutoff': _is_post_cutoff(application),
                    'action_str': f"entering the lottery as a roommate"})

                raise HTTPRedirect('room_group?id={}&action={}&new_conf={}', application.id, "joined", got_new_conf_num)

    @requires_account(LotteryApplication)
    def leave_group(self, session, id=None, message="", **params):
        application = session.lottery_application(id)

        if application.locked:
            raise HTTPRedirect('index?id={}&message={}', application.id,
                               f"You cannot leave your {c.HOTEL_LOTTERY_GROUP_TERM.lower()} at this time.")

        # Once a guest has accepted into a group, only the group leader
        # can remove them. Guests can't self-decline.
        if application.parent_application and application.invite_status == c.INVITE_ACCEPTED:
            raise HTTPRedirect(
                'index?id={}&message={}', application.id,
                "Please contact your {} leader to be removed from this room.".format(
                    c.HOTEL_LOTTERY_GROUP_TERM.lower()))

        if cherrypy.request.method == "POST":
            room_group = application.parent_application

            if room_group.status in [c.COMPLETE, c.PROCESSED, c.AWARDED, c.SECURED]:
                EmailService.queue_email(
                    session, 'hotel_lottery_group_member_left', room_group,
                    subject=f'{application.attendee.first_name} has left your {c.EVENT_NAME} Lottery {c.HOTEL_LOTTERY_GROUP_TERM}',
                    data={
                    'app': room_group, 'member': application})
            
            if room_group.status == c.PROCESSED or room_group.finalized:
                application = _clear_application(application)
            else:
                application = _reset_group_member(application)

            if application.status == c.WITHDRAWN:
                raise HTTPRedirect('{}message={}'.format(_return_link(application.attendee.id),
                                   f'You have left the {c.HOTEL_LOTTERY_GROUP_TERM.lower()} \
                                    "{room_group.room_group_name}" and been removed from the hotel lottery.'))
            raise HTTPRedirect('index?id={}&message={}&confirm={}&action={}',
                               application.id,
                               f'Successfully left the {c.HOTEL_LOTTERY_GROUP_TERM.lower()} "{room_group.room_group_name}".',
                               "suite" if application.entry_type == c.SUITE_ENTRY else "room",
                               're-entered')

    def confirm(self, session, id, assignment_id=None, message='', **params):
        """Redirect to the hotel's booking URL for a specific RoomAssignment.

        `id` is the LotteryApplication id; `assignment_id` picks a specific
        RoomAssignment when the attendee holds more than one. Without it, we
        pick the earliest unsecured primary room.
        """
        application = session.lottery_application(id)
        if application.parent_application or application.valid_group_members:
            you_str = f"Your {c.HOTEL_LOTTERY_GROUP_TERM.lower()}'s"
        else:
            you_str = "Your"

        if application.parent_application:
            raise HTTPRedirect(
                'index?id={}&message={}', id,
                f"Only the leader of your {c.HOTEL_LOTTERY_GROUP_TERM.lower()} "
                "may confirm or edit your room or suite award.")

        ra = None
        if assignment_id:
            ra = session.query(RoomAssignment).get(assignment_id)
            if not ra or ra.lottery_application_id != application.id:
                ra = None
        if not ra:
            ra = (session.query(RoomAssignment)
                  .filter(RoomAssignment.lottery_application_id == application.id,
                          RoomAssignment.parent_assignment_id.is_(None),
                          RoomAssignment.status.in_([c.ASSIGNED, c.SECURED]))
                  .order_by(RoomAssignment.assigned_check_in_date.asc().nullsfirst())
                  .first())

        if not ra:
            raise HTTPRedirect('index?id={}&message={}', id,
                               f"{you_str} entry does not have a room or suite award.")
        booking_url = (ra.inventory.hotel.booking_url
                       if ra.inventory and ra.inventory.hotel else '')
        if not booking_url:
            raise HTTPRedirect(
                'index?id={}&message={}', id,
                f"{you_str} entry is still being processed and the booking "
                "link is not available yet.")
        raise HTTPRedirect(booking_url)

    def decline(self, session, id, assignment_id=None, message='', **params):
        """Cancel one of the attendee's awarded RoomAssignments.

        If a connector primary is cancelled, its connector children cascade.
        If the cancelled assignment is the attendee's last live one, the
        LotteryApplication.status flips back to COMPLETE via the model
        listener.
        """
        application = session.lottery_application(id)
        if application.parent_application or application.valid_group_members:
            you_str = f"Your {c.HOTEL_LOTTERY_GROUP_TERM.lower()}'s"
        else:
            you_str = "Your"

        if application.parent_application:
            raise HTTPRedirect(
                'index?id={}&message={}', id,
                f"Only the leader of your {c.HOTEL_LOTTERY_GROUP_TERM.lower()} "
                "may decline your room or suite award.")

        ra = None
        if assignment_id:
            ra = session.query(RoomAssignment).get(assignment_id)
        if not ra:
            ra = (session.query(RoomAssignment)
                  .filter(RoomAssignment.lottery_application_id == application.id,
                          RoomAssignment.parent_assignment_id.is_(None),
                          RoomAssignment.status == c.ASSIGNED)
                  .order_by(RoomAssignment.assigned_check_in_date.asc().nullsfirst())
                  .first())
        if not ra or ra.lottery_application_id != application.id:
            raise HTTPRedirect('index?id={}&message={}', id,
                               f"{you_str} entry does not have a room or suite award.")

        # Connector rooms can't be declined on their own - they're a
        # mandatory part of the parent suite. Send the attendee to the
        # parent's editor, where declining the suite cancels the
        # connectors along with it.
        if ra.parent_assignment_id:
            raise HTTPRedirect(
                'room?id={}&message={}', ra.parent_assignment_id,
                "Connector rooms are included with your suite and can't be "
                "declined separately. Decline the suite to give up the whole "
                "block.")

        if ra.status == c.SECURED:
            raise HTTPRedirect(
                'index?id={}&message={}', id,
                "You cannot cancel a reservation that has already been "
                "confirmed with a credit card guarantee.")
        if ra.status == c.CANCELLED:
            raise HTTPRedirect(
                'index?id={}&message={}', id,
                "This reservation has already been cancelled.")
        if ra.status != c.ASSIGNED:
            raise HTTPRedirect(
                'index?id={}&message={}', id,
                f"{you_str} entry does not have a room or suite award.")

        room_type = ('suite' if ra.inventory and ra.inventory.is_suite else 'room')

        if cherrypy.request.method == "POST":
            if 'confirm' not in params:
                message = (f"Please check the box confirming that you want to "
                           f"give up {you_str.lower()} {room_type} award.")
                return {'application': application,
                        'assignment': ra,
                        'message': message}

            children = (session.query(RoomAssignment)
                        .filter_by(parent_assignment_id=ra.id).all())
            for child in children:
                child.status = c.CANCELLED
                session.add(child)
            ra.status = c.CANCELLED
            session.add(ra)
            session.commit()

            still_live = (session.query(RoomAssignment)
                          .filter(RoomAssignment.lottery_application_id == application.id,
                                  RoomAssignment.status.in_([c.ASSIGNED, c.SECURED]))
                          .count())
            if still_live == 0:
                message = (f"You have declined your {room_type} award and your "
                           "lottery entry has been cancelled.")
                raise HTTPRedirect('{}message={}'.format(
                    _return_link(application.attendee.id), message))
            raise HTTPRedirect(
                'rooms?attendee_id={}&message={}',
                application.attendee.id,
                f"You have declined your {room_type} award.")

        return {
            'application': application,
            'assignment': ra,
            'message': message,
        }

    def secure_room(self, session, id=None, assignment_id=None, attendee_id='',
                    message='', **params):
        """Render the credit-card capture page for a specific RoomAssignment.

        `assignment_id` picks the room. `id` is the LotteryApplication
        id and is now optional - non-lottery rooms (partition grants,
        department assignments) reach this page too, and they have no
        application to drive the group-leader check off. When `id` is
        absent we resolve the application (if any) from the room itself.

        `attendee_id` is the view-as context, carried through so the
        page's "Back to room" link returns to the right editor.
        """
        if not c.VAULT_ENABLED:
            raise HTTPRedirect(
                'rooms?message={}',
                "Credit card collection is not currently available.")

        ra = None
        if assignment_id:
            ra = session.query(RoomAssignment).get(assignment_id)
        if not ra and id:
            # Legacy callers that only know the application id -
            # pick the earliest unsecured self-pay room on that app.
            application_for_lookup = session.lottery_application(id)
            ra = (session.query(RoomAssignment)
                  .filter(RoomAssignment.lottery_application_id == application_for_lookup.id,
                          RoomAssignment.parent_assignment_id.is_(None),
                          RoomAssignment.status == c.ASSIGNED,
                          RoomAssignment.require_cc.is_(True),
                          RoomAssignment.cc_token.is_(None))
                  .order_by(RoomAssignment.assigned_check_in_date.asc().nullsfirst())
                  .first())
        if not ra:
            raise HTTPRedirect(
                'rooms?message={}',
                "Room not found or no longer needs a credit card.")
        if ra.status not in (c.ASSIGNED, c.SECURED):
            raise HTTPRedirect(
                'rooms?message={}',
                "This room is not in a state that can be secured.")

        application = ra.lottery_application
        # Only block when this attendee is a *guest* in a lottery group -
        # the booker themselves is always allowed. For non-lottery rooms
        # `application` is None and there's no group concept to enforce.
        if application and application.parent_application:
            raise HTTPRedirect(
                'rooms?message={}',
                f"Only the leader of your {c.HOTEL_LOTTERY_GROUP_TERM.lower()} "
                "may secure the room.")

        # Billing-detail copy sources: the booker's OTHER rooms in the
        # same vault scope (same hotel's payment system) that already
        # have both a card on file and a billing address. Selecting one
        # reuses its card and address via copy_booking_info and secures
        # this room without re-entering the card.
        billing_source_rooms = []
        target_ref = _effective_vault_reference(ra)
        siblings = (session.query(RoomAssignment)
                    .filter(RoomAssignment.attendee_id == ra.attendee_id,
                            RoomAssignment.id != ra.id,
                            RoomAssignment.cc_token.isnot(None))
                    .all())
        for other in siblings:
            if not (other.address1 and other.address1.strip()):
                continue
            if _effective_vault_reference(other) != target_ref:
                continue
            inv = other.inventory
            if inv and inv.hotel:
                if inv.is_suite:
                    type_name = inv.suite_type.name if inv.suite_type else inv.name
                else:
                    type_name = inv.room_type.name if inv.room_type else inv.name
                label = f"{inv.hotel.name} - {type_name}"
            else:
                label = "Another room"
            if other.cc_last_four:
                label += f" (card {other.cc_last_four})"
            billing_source_rooms.append({
                'id': str(other.id),
                'label': label,
            })

        return {
            'application': application,
            'assignment': ra,
            'attendee_id': attendee_id,
            'billing_source_rooms': billing_source_rooms,
            'message': message,
        }

    @ajax
    def create_vault_session(self, session, assignment_id=None, id=None):
        """Create a PCI Vault capture session and return the iframe URL.

        Vault reference is scoped to the assignment's inventory's hotel
        (via `vault_reference`), so cards captured for room A at hotel X
        can't be reused at hotel Y.
        """
        if assignment_id:
            ra = session.query(RoomAssignment).get(assignment_id)
        else:
            ra = None
        if not ra:
            return {'error': 'Assignment not found.'}
        if ra.export_locked:
            return {'error': 'This booking has been transferred to the hotel '
                             'and the card on file cannot be changed here.'}
        if ra.status not in (c.ASSIGNED, c.SECURED):
            return {'error': 'This room is not in a state that can be secured.'}

        inventory_item = ra.inventory
        vault_reference = (inventory_item.vault_reference
                           if inventory_item and inventory_item.vault_reference
                           else f"hotel_{inventory_item.hotel_id}" if inventory_item
                           else "default")

        from uber.vault import create_capture_session, get_capture_iframe_url
        capture = create_capture_session(
            reference=vault_reference,
            webhook_metadata={'assignment_id': ra.id},
        )
        iframe_url = get_capture_iframe_url(
            endpoint_id=capture['unique_id'],
            secret=capture['secret'],
            reference=vault_reference,
        )
        return {'success': True, 'iframe_url': iframe_url}

    @ajax
    def save_card_token(self, session, token, assignment_id=None, id=None,
                        last_four='', card_type='', **params):
        """Save just the card token without requiring address or changing status."""
        from pytz import UTC
        if not assignment_id:
            return {'error': 'Assignment not found.'}
        ra = session.query(RoomAssignment).get(assignment_id)
        if not ra:
            return {'error': 'Assignment not found.'}
        if ra.export_locked:
            return {'error': 'This booking has been transferred to the hotel '
                             'and the card on file cannot be changed here.'}
        if ra.status not in (c.ASSIGNED, c.SECURED):
            return {'error': 'This room is not in a state that can be secured.'}
        if not token:
            return {'error': 'No card token received.'}

        ra.cc_token = token
        ra.cc_last_four = last_four
        ra.cc_card_type = card_type
        ra.cc_captured_at = datetime.now(UTC)

        session.add(ra)
        session.commit()
        return {'success': True}

    @ajax
    def secure_room_callback(self, session, token, assignment_id=None, id=None,
                             last_four='', card_type='', **params):
        from pytz import UTC
        if not assignment_id:
            return {'error': 'Assignment not found.'}
        ra = session.query(RoomAssignment).get(assignment_id)
        if not ra:
            return {'error': 'Assignment not found.'}
        if ra.export_locked:
            return {'error': 'This booking has been transferred to the hotel '
                             'and the card on file cannot be changed here.'}
        if ra.status not in (c.ASSIGNED, c.SECURED):
            return {'error': 'This room is not in a state that can be secured.'}
        if not token:
            return {'error': 'No card token received.'}

        # Require billing address
        address1 = params.get('address1', '').strip()
        city = params.get('city', '').strip()
        region = params.get('region', '').strip()
        zip_code = params.get('zip_code', '').strip()
        country = params.get('country', '').strip()

        if not all([address1, city, region, zip_code, country]):
            return {'error': 'Please fill in all required billing address fields.'}

        ra.cc_token = token
        ra.cc_last_four = last_four
        ra.cc_card_type = card_type
        ra.cc_captured_at = datetime.now(UTC)
        ra.status = c.SECURED

        ra.address1 = address1
        ra.address2 = params.get('address2', '').strip()
        ra.city = city
        ra.region = region
        ra.zip_code = zip_code
        ra.country = country

        application = ra.lottery_application
        if application:
            application.hotel_rewards_number = params.get(
                'hotel_rewards_number', '').strip()
            session.add(application)

        # Handle date choice: accept assigned dates or request waitlist
        from dateutil import parser as dateparser
        date_choice = params.get('date_choice', 'accept')
        if date_choice == 'waitlist' and application:
            requested_ci = params.get('requested_checkin', '')
            requested_co = params.get('requested_checkout', '')
            try:
                if requested_ci and ra.assigned_check_in_date:
                    new_ci = dateparser.parse(requested_ci).date()
                    if new_ci <= ra.assigned_check_in_date:
                        application.earliest_checkin_date = new_ci
                if requested_co and ra.assigned_check_out_date:
                    new_co = dateparser.parse(requested_co).date()
                    if new_co >= ra.assigned_check_out_date:
                        application.latest_checkout_date = new_co
            except (ValueError, OverflowError):
                return {'error': 'Invalid date format.'}
        elif application:
            # Accept: set requested dates to match assigned - no waitlist
            if ra.assigned_check_in_date:
                application.earliest_checkin_date = ra.assigned_check_in_date
            if ra.assigned_check_out_date:
                application.latest_checkout_date = ra.assigned_check_out_date

        # Connector children are NOT cascade-secured here. Each room - suite
        # and every connector - carries its own card on file and is secured
        # independently from its own row in the attendee rooms view, so each
        # is a separate booking end to end.
        session.add(ra)
        session.commit()
        return {'success': True}

    @ajax_gettable
    def vault_webhook(self, session, **params):
        """Webhook called by PCI Vault after a card is captured.

        Updates card metadata from the webhook payload. Structure:
        {
          "metadata": {"application_id": "..."},
          "token_info": {
            "token": "...",
            "safe_data": "{\"card_holder\": ..., \"last_four\": ..., \"card_type\": ...}",
            "card_metadata": {"issuer": [{"brand": ..., "issuing_bank": ..., ...}]},
            ...
          }
        }
        """
        # Verify webhook secret
        import hmac
        webhook_secret = cherrypy.request.headers.get('X-PCIVault-Webhook-Secret', '')
        if not c.VAULT_WEBHOOK_SECRET or not hmac.compare_digest(webhook_secret, c.VAULT_WEBHOOK_SECRET):
            cherrypy.response.status = 403
            return {'error': 'Invalid webhook secret'}

        # Parse JSON body
        try:
            body = json.loads(cherrypy.request.body.read())
        except Exception:
            cherrypy.response.status = 400
            return {'error': 'Invalid JSON body'}

        metadata = body.get('metadata', {})
        assignment_id = metadata.get('assignment_id', '')
        token_info = body.get('token_info', {})
        token = token_info.get('token', '')

        if not token or not assignment_id:
            cherrypy.response.status = 400
            return {'error': 'Missing token or assignment_id'}

        ra = session.query(RoomAssignment).get(assignment_id)
        if not ra:
            cherrypy.response.status = 404
            return {'error': 'Assignment not found'}

        # Only update if the token matches what we have stored
        if ra.cc_token != token:
            return {'success': True}

        # Parse safe_data (JSON string with card holder, last four, etc.)
        try:
            safe_data = json.loads(token_info.get('safe_data', '{}'))
        except (json.JSONDecodeError, TypeError):
            safe_data = {}

        if safe_data.get('last_four'):
            ra.cc_last_four = safe_data['last_four']
        if safe_data.get('card_type'):
            ra.cc_card_type = safe_data['card_type']
        if safe_data.get('card_holder'):
            ra.cc_card_holder = safe_data['card_holder']
        if safe_data.get('expiry'):
            ra.cc_card_expiry = safe_data['expiry']

        # Parse issuer metadata
        card_metadata = token_info.get('card_metadata', {})
        issuers = card_metadata.get('issuer', [])
        if issuers and isinstance(issuers, list):
            issuer = issuers[0]
            if issuer.get('brand'):
                ra.cc_issuer_brand = issuer['brand']
            if issuer.get('issuing_bank'):
                ra.cc_issuer_bank = issuer['issuing_bank']
            if issuer.get('country_name'):
                ra.cc_issuer_country = issuer['country_name']
            if issuer.get('card_type'):
                ra.cc_issuer_card_type = issuer['card_type']
            if issuer.get('card_level'):
                ra.cc_issuer_card_level = issuer['card_level']

        session.add(ra)
        session.commit()

        return {'success': True}

    def edit_room(self, session, id, assignment_id=None, attendee_id='',
                  message='', **params):
        """Edit a specific RoomAssignment's check-in/out dates and special
        requests. Connector rooms inherit their dates from the parent.

        `attendee_id` is forwarded on the redirect back to the per-room
        editor so admin view-as-attendee context survives the round-trip.
        """
        application = session.lottery_application(id)

        if application.parent_application:
            raise HTTPRedirect(
                'index?attendee_id={}&message={}', application.attendee.id,
                f"Only the leader of your {c.HOTEL_LOTTERY_GROUP_TERM.lower()} "
                "may edit the room.")

        ra = None
        if assignment_id:
            ra = session.query(RoomAssignment).get(assignment_id)
        if not ra:
            ra = (session.query(RoomAssignment)
                  .filter(RoomAssignment.lottery_application_id == application.id,
                          RoomAssignment.parent_assignment_id.is_(None),
                          RoomAssignment.status.in_([c.ASSIGNED, c.SECURED]))
                  .order_by(RoomAssignment.assigned_check_in_date.asc().nullsfirst())
                  .first())
        if not ra or ra.lottery_application_id != application.id:
            raise HTTPRedirect(
                'index?attendee_id={}&message={}', application.attendee.id,
                "Your entry does not have a room award to edit.")

        if ra.parent_assignment_id:
            # Connector rooms follow the parent's dates - redirect to it.
            raise HTTPRedirect(
                'edit_room?id={}&assignment_id={}&message={}',
                application.id, ra.parent_assignment_id,
                "Connector rooms inherit their dates from the parent room.")

        if cherrypy.request.method == "POST":
            if ra.export_locked:
                raise HTTPRedirect(
                    'edit_room?id={}&assignment_id={}&message={}', id, ra.id,
                    'Your room details have been exported to the hotel and '
                    'cannot be changed. Please contact us for assistance.')

            from dateutil import parser as dateparser
            from datetime import timedelta as td

            new_check_in = params.get('assigned_check_in_date')
            new_check_out = params.get('assigned_check_out_date')
            special_requests = params.get('special_requests', '')

            inv = ra.inventory

            # Availability check with partial confirmation + waitlist
            if new_check_in and new_check_out and inv:
                new_ci = dateparser.parse(new_check_in).date()
                new_co = dateparser.parse(new_check_out).date()
                nq_map = inv.night_quantity_map

                part_id = ra.partition_id
                if part_id:
                    pb = session.query(InventoryPartitionBlock).filter_by(
                        partition_id=part_id, inventory_id=inv.id).first()
                    partition_cap = pb.quantity if pb else 0
                else:
                    total_partitioned = session.query(
                        func.coalesce(func.sum(InventoryPartitionBlock.quantity), 0)
                    ).filter(InventoryPartitionBlock.inventory_id == str(inv.id)).scalar()

                # Look up who else is already on the waitlist for this
                # block - FIFO fairness. If anyone is waiting, the
                # attendee's *new* extension nights queue behind them
                # even when raw capacity is technically free for that
                # night (the cron will sort it all out, but only after
                # earlier waitlisters get served first).
                #
                # We only care about other rooms (not this one), and
                # only about rooms that still have outstanding waitlist
                # demand (`waitlisted_*` non-NULL).
                others_on_waitlist = session.query(RoomAssignment).filter(
                    RoomAssignment.inventory_id == ra.inventory_id,
                    RoomAssignment.id != ra.id,
                    sa.or_(
                        RoomAssignment.waitlisted_check_in_date.isnot(None),
                        RoomAssignment.waitlisted_check_out_date.isnot(None)),
                ).count() > 0

                # Which extension nights does the attendee want that are
                # OUTSIDE the currently-assigned range? Only those need
                # the FIFO check; nights already inside the assigned
                # range are just being preserved (or, on a shrink, the
                # extension set is empty).
                cur_ci = ra.assigned_check_in_date
                cur_co = ra.assigned_check_out_date

                def _is_extension_night(d):
                    if not (cur_ci and cur_co):
                        return True
                    return d < cur_ci or d >= cur_co

                available_nights = []
                unavailable_nights = []
                day = new_ci
                while day < new_co:
                    block_qty = nq_map.get(day, inv.quantity) if nq_map else inv.quantity
                    if part_id:
                        capacity = min(partition_cap, block_qty)
                    else:
                        capacity = max(0, block_qty - total_partitioned)

                    part_filter = ((RoomAssignment.partition_id == part_id)
                                   if part_id else
                                   (RoomAssignment.partition_id.is_(None)))
                    assigned_count = session.query(RoomAssignment).filter(
                        RoomAssignment.inventory_id == ra.inventory_id,
                        RoomAssignment.status.in_([c.ASSIGNED, c.SECURED]),
                        RoomAssignment.id != ra.id,
                        RoomAssignment.assigned_check_in_date <= day,
                        RoomAssignment.assigned_check_out_date > day,
                        part_filter,
                    ).count()
                    # An extension night is waitlisted if EITHER the
                    # block is over capacity for that night OR there's
                    # already someone queued ahead on this block.
                    blocked_by_queue = (others_on_waitlist
                                        and _is_extension_night(day))
                    if assigned_count >= capacity or blocked_by_queue:
                        unavailable_nights.append(day)
                    else:
                        available_nights.append(day)
                    day += td(days=1)

                # Determine the confirmed contiguous range (must include current assigned range)
                confirmed_ci = ra.assigned_check_in_date
                confirmed_co = ra.assigned_check_out_date

                if new_ci < confirmed_ci:
                    d = confirmed_ci - td(days=1)
                    while d >= new_ci and d in available_nights:
                        confirmed_ci = d
                        d -= td(days=1)

                if new_co > confirmed_co:
                    d = confirmed_co
                    while d < new_co and d in available_nights:
                        confirmed_co = d + td(days=1)
                        d += td(days=1)

                ra.assigned_check_in_date = confirmed_ci
                ra.assigned_check_out_date = confirmed_co

                # Per-room waitlist: stash the wider desired window on
                # the assignment itself. NOT on `application.earliest_*` /
                # `latest_*` - those represent the original lottery entry
                # and shouldn't shift every time the attendee retunes
                # the dates on one of their rooms.
                #
                # Clear the columns when the confirmed range already
                # matches the request so the row drops out of the
                # waitlist queue. (The model's `clear_waitlist_when_satisfied`
                # presave handles the same cleanup when the cron extends
                # assigned_*, but we mirror it here so the immediate
                # post-edit state is consistent before the next request.)
                if (confirmed_ci > new_ci) or (confirmed_co < new_co):
                    ra.waitlisted_check_in_date = new_ci
                    ra.waitlisted_check_out_date = new_co
                else:
                    ra.waitlisted_check_in_date = None
                    ra.waitlisted_check_out_date = None

                # Cascade dates to connector children - they always
                # match parent, including waitlist state.
                children = (session.query(RoomAssignment)
                            .filter_by(parent_assignment_id=ra.id).all())
                for child in children:
                    child.assigned_check_in_date = confirmed_ci
                    child.assigned_check_out_date = confirmed_co
                    child.waitlisted_check_in_date = ra.waitlisted_check_in_date
                    child.waitlisted_check_out_date = ra.waitlisted_check_out_date
                    session.add(child)

                if unavailable_nights:
                    wl_strs = [d.strftime('%a %-m/%-d') for d in unavailable_nights]
                    message = (f"Confirmed: {confirmed_ci.strftime('%a %-m/%-d')} - "
                               f"{confirmed_co.strftime('%a %-m/%-d')}. "
                               f"Waitlisted: {', '.join(wl_strs)}. "
                               f"You'll be notified if availability opens up.")
                else:
                    message = 'Room details updated.'
            else:
                if new_check_in:
                    ra.assigned_check_in_date = dateparser.parse(new_check_in).date()
                if new_check_out:
                    ra.assigned_check_out_date = dateparser.parse(new_check_out).date()

            ra.special_requests = special_requests
            application.hotel_rewards_number = params.get('hotel_rewards_number', '').strip()

            # Address fields live on the RoomAssignment.
            ra.address1 = params.get('address1', '').strip()
            ra.address2 = params.get('address2', '').strip()
            ra.city = params.get('city', '').strip()
            ra.region = params.get('region', '').strip()
            ra.zip_code = params.get('zip_code', '').strip()
            ra.country = params.get('country', '').strip()

            session.add(ra)
            session.add(application)
            session.commit()
            if not message:
                message = 'Room details updated.'
            raise HTTPRedirect(_room_url(
                ra.id,
                attendee_id or application.attendee.id,
                message=message))

        inventory_item = ra.inventory
        max_guests = inventory_item.capacity - 1 if inventory_item else 3

        return {
            'application': application,
            'assignment': ra,
            'max_guests': max_guests,
            'vault_enabled': c.VAULT_ENABLED,
            'message': message,
        }

    # Per-room occupants live on `room_assignment_occupant` and are managed
    # via the RoomAssignmentInvite flow (the `invite_email` / `invite_code` /
    # `invite` / `redeem_code` / `remove_occupant` / `leave_room` /
    # `copy_occupants` handlers below). `invite_room_guest` /
    # `remove_room_guest` are redirect stubs so old links return a graceful
    # "moved" notice.

    def invite_room_guest(self, session, id, email='', **params):
        raise HTTPRedirect(
            'room?id={}&message={}', id,
            'Guest management has moved to the per-room editor.')

    def remove_room_guest(self, session, id, member_id, **params):
        raise HTTPRedirect(
            'room?id={}&message={}', id,
            'Guest management has moved to the per-room editor.')

    @requires_account(Attendee)
    def send_room_invite(self, session, id, email='', **params):
        application = session.lottery_application(id)
        message = ''

        if application.parent_application:
            message = f"Only the leader of a {c.HOTEL_LOTTERY_GROUP_TERM.lower()} may send invites."
        elif not application.room_group_name:
            message = f"You must create a {c.HOTEL_LOTTERY_GROUP_TERM.lower()} before sending invites."
        else:
            max_group = _max_room_capacity_for_group(session, application)
            if len(application.valid_group_members) >= max_group:
                message = f"Your {c.HOTEL_LOTTERY_GROUP_TERM.lower()} is full."
            elif not email:
                message = "Please enter an email address."
            else:
                normalized = normalize_email_legacy(email)
                guest_attendee = session.query(Attendee).filter(
                    Attendee.normalized_email == normalized
                ).first()

                if not guest_attendee:
                    message = "No attendee found with that email address. Please check the address and try again."
                else:
                    guest_app = getattr(guest_attendee, 'lottery_application', None)
                    if not guest_app:
                        # Legal names live on the attendee
                        # (hotel_first_name / hotel_last_name), not on the
                        # LotteryApplication.
                        guest_app = LotteryApplication(
                            attendee_id=guest_attendee.id,
                            status=c.COMPLETE,
                            entry_type=c.GROUP_ENTRY,
                            cellphone=guest_attendee.cellphone,
                        )
                        session.add(guest_app)
                        session.flush()
                    if guest_app.id == application.id:
                        message = "You cannot invite yourself."
                    elif guest_app.parent_application_id:
                        message = f"That attendee is already in a {c.HOTEL_LOTTERY_GROUP_TERM.lower()}."
                    elif guest_app.invite_status == c.INVITE_PENDING:
                        message = "That attendee already has a pending invite."
                    else:
                        token = str(uuid.uuid4())
                        guest_app.invite_token = token
                        guest_app.invited_by_id = application.id
                        guest_app.invite_status = c.INVITE_PENDING
                        guest_app.invite_expires_at = datetime.now() + timedelta(days=7)
                        session.add(guest_app)
                        session.commit()

                        # Send invite email
                        from uber.decorators import render
                        EmailService.queue_email(
                            session, 'room_guest_invite', guest_app,
                            subject=f'{c.EVENT_NAME} Hotel {c.HOTEL_LOTTERY_GROUP_TERM} Invite from {application.group_leader_name}',
                            data={
                            'app': guest_app,
                            'leader': application,
                            'token': token,
                        })

                        raise HTTPRedirect('room_group?id={}&message={}', id,
                                           f'Invite sent to {email}.')

        raise HTTPRedirect('room_group?id={}&message={}', id, message)

    @requires_account(Attendee)
    def accept_invite(self, session, token, attendee_id=None, **params):
        if not token:
            raise HTTPRedirect('../preregistration/homepage?message={}', 'Invalid invite link.')

        guest_app = session.query(LotteryApplication).filter_by(invite_token=token).first()
        if not guest_app:
            raise HTTPRedirect('../preregistration/homepage?message={}', 'Invite not found or already used.')

        if guest_app.invite_status != c.INVITE_PENDING:
            raise HTTPRedirect('../preregistration/homepage?message={}',
                               f'This invite has been {guest_app.invite_status_label.lower()}.')

        if guest_app.invite_expires_at and guest_app.invite_expires_at < datetime.now():
            guest_app.invite_status = c.INVITE_EXPIRED
            session.add(guest_app)
            session.commit()
            raise HTTPRedirect('../preregistration/homepage?message={}', 'This invite has expired.')

        leader_app = session.lottery_application(guest_app.invited_by_id)

        if cherrypy.request.method == 'POST':
            if guest_app.parent_application_id:
                raise HTTPRedirect('../preregistration/homepage?message={}',
                                   f'You are already in a {c.HOTEL_LOTTERY_GROUP_TERM.lower()}.')

            msg, _ = _join_room_group(session, guest_app, leader_app.id)
            if msg:
                raise HTTPRedirect('accept_invite?token={}&message={}', token, msg)

            guest_app.invite_status = c.INVITE_ACCEPTED
            guest_app.invite_token = ''
            session.add(guest_app)
            session.commit()
            raise HTTPRedirect('index?attendee_id={}&message={}', guest_app.attendee.id,
                               f'You have joined {leader_app.room_group_name}!')

        return {
            'guest_app': guest_app,
            'leader_app': leader_app,
            'token': token,
        }

    @requires_account(Attendee)
    def cancel_invite(self, session, id, invite_app_id, **params):
        application = session.lottery_application(id)
        invite_app = session.lottery_application(invite_app_id)

        if str(invite_app.invited_by_id) != str(application.id):
            raise HTTPRedirect('room_group?id={}&message={}', id, 'That invite does not belong to your group.')

        invite_app.invite_status = c.INVITE_CANCELLED
        invite_app.invite_token = ''
        invite_app.invited_by_id = None
        session.add(invite_app)
        session.commit()
        raise HTTPRedirect('room_group?id={}&message={}', id, 'Invite cancelled.')

