"""Overflow reveals: who gets a link, and the rule that the destination URL
never reaches a client before the reveal time."""

from datetime import datetime, timedelta

import pytest
from pytz import UTC

from uber.config import c
from uber.models import Attendee
from uber.models.hotel import LotteryApplication, OverflowReveal, OverflowRevealLink

from tests.hotel.factories import (make_application, make_assignment, make_attendee, make_hotel,
                                   make_inventory)


@pytest.fixture(autouse=True)
def clean_reveals(session):
    """The attendee-facing payload builder commits when it stamps a click, so
    the session fixture's rollback cannot undo these rows. Clear them here or
    they accumulate across runs and collide on the shared-token index.
    """
    yield
    session.rollback()
    session.query(OverflowRevealLink).delete()
    session.query(OverflowReveal).delete()
    # Those commits take the whole session with them, attendees included.
    session.query(LotteryApplication).delete()
    session.query(Attendee).delete()
    session.commit()


LINKS = [
    {'label': 'Hotel A', 'url': 'https://a.example.com/secret'},
    {'label': 'Hotel B', 'url': 'https://b.example.com/secret'},
    {'label': '', 'url': 'https://c.example.com/secret'},
]


def _reveal(session, **kwargs):
    kwargs.setdefault('name', 'Test reveal')
    kwargs.setdefault('booking_links', [dict(item) for item in LINKS])
    kwargs.setdefault('active', True)
    reveal = OverflowReveal(**kwargs)
    session.add(reveal)
    session.flush()
    return reveal


def _eligible_attendee(session, status=c.COMPLETE):
    """Lottery-eligible, entered at `status`, and holding no live room."""
    attendee = make_attendee(session)
    attendee.paid = c.HAS_PAID
    attendee.badge_status = c.COMPLETED_STATUS
    attendee.placeholder = False
    session.flush()
    make_application(session, attendee, status=status)
    return attendee


def _roommate(session, leader):
    member = _eligible_attendee(session)
    member.lottery_application.entry_type = c.GROUP_ENTRY
    member.lottery_application.parent_application_id = leader.lottery_application.id
    session.flush()
    return member


def _candidates(session, reveal):
    from uber.site_sections.hotel_lottery_admin import _overflow_reveal_candidates
    return _overflow_reveal_candidates(session, reveal)


# ---------------------------------------------------------------------------
# who is a candidate
# ---------------------------------------------------------------------------

def test_attendee_with_a_live_room_is_not_a_candidate(session, no_cherrypy_session):
    reveal = _reveal(session)
    hotel = make_hotel(session)
    inv = make_inventory(session, hotel)
    roomed = _eligible_attendee(session)
    make_assignment(session, attendee=roomed, inventory=inv)
    session.flush()

    eligible, _emailed, _pending, _new = _candidates(session, reveal)
    assert roomed.id not in eligible


def test_attendee_who_never_applied_is_not_a_candidate(session, no_cherrypy_session):
    reveal = _reveal(session)
    attendee = make_attendee(session)
    session.flush()

    eligible, _emailed, _pending, _new = _candidates(session, reveal)
    assert attendee.id not in eligible


@pytest.mark.parametrize('status, expected', [
    (c.COMPLETE, True),
    (c.PROCESSED, True),
    (c.REJECTED, True),
    (c.REMOVED, True),
    (c.PARTIAL, False),
    (c.WITHDRAWN, False),
    (c.DISQUALIFIED, False),
    (c.CANCELLED, False),
])
def test_only_entered_applications_are_candidates(
        session, no_cherrypy_session, status, expected):
    reveal = _reveal(session)
    attendee = _eligible_attendee(session, status=status)

    eligible, _emailed, _pending, _new = _candidates(session, reveal)
    assert (attendee.id in eligible) is expected


def test_listed_occupant_of_a_live_room_is_not_a_candidate(session, no_cherrypy_session):
    reveal = _reveal(session)
    inv = make_inventory(session, make_hotel(session))
    booker = _eligible_attendee(session)
    guest = _eligible_attendee(session)
    ra = make_assignment(session, attendee=booker, inventory=inv)
    ra.occupants = [booker, guest]
    session.flush()

    eligible, _emailed, _pending, _new = _candidates(session, reveal)
    assert guest.id not in eligible


def test_roommate_follows_the_leaders_entry(session, no_cherrypy_session):
    reveal = _reveal(session)
    inv = make_inventory(session, make_hotel(session))

    winner = _eligible_attendee(session)
    make_assignment(session, attendee=winner, inventory=inv,
                    lottery_application_id=winner.lottery_application.id)
    winning_mate = _roommate(session, winner)

    loser = _eligible_attendee(session)
    losing_mate = _roommate(session, loser)

    withdrawn = _eligible_attendee(session, status=c.WITHDRAWN)
    withdrawn_mate = _roommate(session, withdrawn)

    eligible, _emailed, _pending, _new = _candidates(session, reveal)
    assert winning_mate.id not in eligible
    assert losing_mate.id in eligible
    assert withdrawn_mate.id not in eligible


def test_generate_then_send_still_emails(session, no_cherrypy_session):
    """The sender skips on emailed_at, not on the row existing. Skipping on
    the row would mean generating links first made a later send reach nobody.
    """
    reveal = _reveal(session)
    attendee = _eligible_attendee(session)
    session.flush()

    _eligible, _emailed, _pending, new_ids = _candidates(session, reveal)
    assert attendee.id in new_ids

    # Generate without emailing.
    session.add(OverflowRevealLink(overflow_reveal_id=reveal.id,
                                   attendee_id=attendee.id, token='generated'))
    session.flush()

    _eligible, emailed, pending, new_ids = _candidates(session, reveal)
    assert attendee.id in pending, 'awaiting send'
    assert attendee.id not in emailed
    assert attendee.id not in new_ids, 'the row already exists'

    # What the sender would actually mail is pending + new, which still
    # includes this attendee.
    assert attendee.id in list(pending) + new_ids


def test_sending_twice_emails_nobody_new(session, no_cherrypy_session):
    reveal = _reveal(session)
    attendee = _eligible_attendee(session)
    session.add(OverflowRevealLink(overflow_reveal_id=reveal.id,
                                   attendee_id=attendee.id, token='sent',
                                   emailed_at=datetime.now(UTC)))
    session.flush()

    _eligible, emailed, pending, new_ids = _candidates(session, reveal)
    assert attendee.id in emailed
    assert attendee.id not in list(pending) + new_ids, 'nothing left to send them'


# ---------------------------------------------------------------------------
# the reveal-time invariant
# ---------------------------------------------------------------------------

class _Payload:
    """Drives the ajax endpoint's payload builder directly.

    Unwrapping strips the session, rendering, and JSON decorators, so the
    payload can be inspected as data.
    """
    def __init__(self, session):
        from uber.site_sections.hotel_lottery import Root
        func = Root.overflow_reveal
        while hasattr(func, '__wrapped__'):
            func = func.__wrapped__
        self.func = func
        self.root = Root()
        self.session = session

    def get(self, token):
        return self.func(self.root, self.session, token)


@pytest.mark.parametrize('use_unique_links', [True, False])
@pytest.mark.parametrize('require_login', [True, False])
def test_url_is_never_sent_before_the_reveal_time(
        session, no_cherrypy_session, use_unique_links, require_login):
    reveal = _reveal(session,
                     reveal_at=datetime.now(UTC) + timedelta(hours=2),
                     use_unique_links=use_unique_links,
                     require_login=require_login,
                     shared_token='' if use_unique_links else 'shared-token')
    attendee = _eligible_attendee(session)
    link = OverflowRevealLink(overflow_reveal_id=reveal.id,
                              attendee_id=attendee.id, token='unique-token')
    session.add(link)
    session.flush()

    token = 'unique-token' if use_unique_links else 'shared-token'
    payload = _Payload(session).get(token)

    assert not payload.get('booking_links')
    assert payload.get('is_revealed') is not True
    assert 'example.com' not in str(payload)


def test_url_appears_once_revealed(session, no_cherrypy_session):
    reveal = _reveal(session, reveal_at=datetime.now(UTC) - timedelta(minutes=1))
    attendee = _eligible_attendee(session)
    session.add(OverflowRevealLink(overflow_reveal_id=reveal.id,
                                   attendee_id=attendee.id, token='tok'))
    session.flush()

    payload = _Payload(session).get('tok')
    assert payload['is_revealed'] is True
    assert payload['booking_links'] == LINKS


def test_a_shared_token_resolves(session, no_cherrypy_session):
    reveal = _reveal(session, reveal_at=datetime.now(UTC) - timedelta(minutes=1),
                     use_unique_links=False, shared_token='shared-abc')
    session.flush()

    payload = _Payload(session).get('shared-abc')
    assert payload['is_revealed'] is True
    assert payload['booking_links'] == LINKS


def test_shared_views_are_counted_in_aggregate(session, no_cherrypy_session):
    reveal = _reveal(session, reveal_at=datetime.now(UTC) - timedelta(minutes=1),
                     use_unique_links=False, shared_token='shared-xyz')
    session.flush()

    payload_helper = _Payload(session)
    payload_helper.get('shared-xyz')
    payload_helper.get('shared-xyz')
    assert reveal.shared_clicks == 2


def test_an_empty_shared_token_matches_nothing(session, no_cherrypy_session):
    """Every reveal defaults to an empty shared_token, so a blank token must
    not resolve to an arbitrary one."""
    _reveal(session, use_unique_links=False, shared_token='')
    session.flush()

    assert _Payload(session).get('')['error'] == 'missing-token'


def test_an_inactive_reveal_is_refused(session, no_cherrypy_session):
    reveal = _reveal(session, active=False,
                     reveal_at=datetime.now(UTC) - timedelta(minutes=1))
    attendee = _eligible_attendee(session)
    session.add(OverflowRevealLink(overflow_reveal_id=reveal.id,
                                   attendee_id=attendee.id, token='tok-inactive'))
    session.flush()

    assert _Payload(session).get('tok-inactive')['error'] == 'inactive'


# ---------------------------------------------------------------------------
# booking link entry
# ---------------------------------------------------------------------------

def test_booking_links_parse_labels_and_bare_urls():
    text = """
    Hotel A | https://a.example.com/secret

    https://c.example.com/secret
    """
    assert OverflowReveal.parse_booking_links(text) == [
        {'label': 'Hotel A', 'url': 'https://a.example.com/secret'},
        {'label': '', 'url': 'https://c.example.com/secret'},
    ]


@pytest.mark.parametrize('line', [
    'Hotel A | a.example.com/secret',
    'Hotel A | javascript:alert(1)',
    'Hotel A |',
])
def test_booking_links_reject_non_http_urls(line):
    with pytest.raises(ValueError, match='Not a valid'):
        OverflowReveal.parse_booking_links(line)


def test_booking_links_text_round_trips():
    reveal = OverflowReveal(booking_links=[dict(item) for item in LINKS])
    reveal.booking_links_text = reveal.booking_links_text
    assert reveal.booking_links == LINKS


# ---------------------------------------------------------------------------
# sign-in enforcement
# ---------------------------------------------------------------------------

@pytest.fixture
def viewer(monkeypatch):
    """Sign a viewer in the way Keycloak does: account ids on the request,
    nothing in the cherrypy session. Returns a setter."""
    import cherrypy
    from uber.models import initialize_db
    initialize_db()
    monkeypatch.setattr(cherrypy, 'session', {}, raising=False)
    monkeypatch.setattr(c, 'HAS_HOTEL_LOTTERY_ADMIN_ACCESS', False, raising=False)
    monkeypatch.setattr(c, 'ATTENDEE_ACCOUNTS_ENABLED', True, raising=False)

    def login(attendee_account=None, admin_account=None):
        monkeypatch.setattr(cherrypy.request, 'attendee_account',
                            attendee_account.id if attendee_account else None,
                            raising=False)
        monkeypatch.setattr(cherrypy.request, 'admin_account',
                            admin_account.id if admin_account else None,
                            raising=False)
    login()
    return login


def _account_for(session, attendee):
    import uuid
    from uber.models import AttendeeAccount
    account = AttendeeAccount(email=f'acct-{uuid.uuid4().hex[:8]}@example.com')
    session.add(account)
    session.flush()
    account.attendees.append(attendee)
    session.flush()
    return account


def _access_error(session, reveal, link):
    from uber.site_sections.hotel_lottery import Root
    func = Root._reveal_access_error
    while hasattr(func, '__wrapped__'):
        func = func.__wrapped__
    return func(Root(), session, reveal, link)


def _locked_link(session, **reveal_kwargs):
    reveal_kwargs.setdefault('require_login', True)
    reveal = _reveal(session, **reveal_kwargs)
    owner = _eligible_attendee(session)
    link = OverflowRevealLink(overflow_reveal_id=reveal.id,
                              attendee_id=owner.id, token='locked-token')
    session.add(link)
    session.flush()
    return reveal, link, owner


def test_signed_out_viewer_is_asked_to_sign_in(session, viewer):
    reveal, link, _owner = _locked_link(session)
    assert _access_error(session, reveal, link) == 'login-required'


def test_owner_account_sees_the_reveal(session, viewer):
    reveal, link, owner = _locked_link(session)
    viewer(attendee_account=_account_for(session, owner))
    assert _access_error(session, reveal, link) is None


def test_forwarded_link_is_refused_as_wrong_account(session, viewer):
    reveal, link, _owner = _locked_link(session)
    stranger = _eligible_attendee(session)
    viewer(attendee_account=_account_for(session, stranger))
    assert _access_error(session, reveal, link) == 'wrong-account'


def test_staffer_admin_login_owns_their_own_link(session, viewer):
    from uber.models import AdminAccount
    reveal, link, owner = _locked_link(session)
    admin = AdminAccount(attendee=owner, hashed='x')
    session.add(admin)
    session.flush()
    viewer(admin_account=admin)
    assert _access_error(session, reveal, link) is None


def test_sign_in_is_not_enforced_when_the_reveal_does_not_ask(session, viewer):
    reveal, link, _owner = _locked_link(session, require_login=False)
    assert _access_error(session, reveal, link) is None


def test_sign_in_is_not_enforced_without_attendee_accounts(session, viewer, monkeypatch):
    reveal, link, _owner = _locked_link(session)
    monkeypatch.setattr(c, 'ATTENDEE_ACCOUNTS_ENABLED', False, raising=False)
    assert not reveal.enforces_login
    assert _access_error(session, reveal, link) is None
