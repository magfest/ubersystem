"""Waitlist reveals: who gets a link, and the rule that the destination URL
never reaches a client before the reveal time."""

from datetime import datetime, timedelta

import pytest
from pytz import UTC

from uber.config import c
from uber.models import Attendee
from uber.models.hotel import WaitlistReveal, WaitlistRevealLink

from tests.hotel.factories import (make_assignment, make_attendee, make_hotel,
                                   make_inventory)


@pytest.fixture(autouse=True)
def clean_reveals(session):
    """The attendee-facing payload builder commits when it stamps a click, so
    the session fixture's rollback cannot undo these rows. Clear them here or
    they accumulate across runs and collide on the shared-token index.
    """
    yield
    session.rollback()
    session.query(WaitlistRevealLink).delete()
    session.query(WaitlistReveal).delete()
    # Those commits take the whole session with them, attendees included.
    session.query(Attendee).delete()
    session.commit()


def _reveal(session, **kwargs):
    kwargs.setdefault('name', 'Test reveal')
    kwargs.setdefault('external_url', 'https://book.example.com/secret')
    kwargs.setdefault('active', True)
    reveal = WaitlistReveal(**kwargs)
    session.add(reveal)
    session.flush()
    return reveal


def _eligible_attendee(session):
    """Lottery-eligible and holding no live room."""
    attendee = make_attendee(session)
    attendee.paid = c.HAS_PAID
    attendee.badge_status = c.COMPLETED_STATUS
    attendee.placeholder = False
    session.flush()
    return attendee


def _candidates(session, reveal):
    from uber.site_sections.hotel_lottery_admin import _waitlist_reveal_candidates
    return _waitlist_reveal_candidates(session, reveal)


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
    session.add(WaitlistRevealLink(waitlist_reveal_id=reveal.id,
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
    session.add(WaitlistRevealLink(waitlist_reveal_id=reveal.id,
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
    """Drives the payload builder directly.

    all_renderable wraps every method on Root, including this one, and the
    wrapper tries to render a template named after it. Unwrapping gets at the
    plain function so the payload can be inspected as data.
    """
    def __init__(self, session):
        from uber.site_sections.hotel_lottery import Root
        func = Root._waitlist_reveal_payload
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
    link = WaitlistRevealLink(waitlist_reveal_id=reveal.id,
                              attendee_id=attendee.id, token='unique-token')
    session.add(link)
    session.flush()

    token = 'unique-token' if use_unique_links else 'shared-token'
    payload = _Payload(session).get(token)

    assert payload.get('external_url') is None
    assert payload.get('is_revealed') is not True
    assert 'book.example.com' not in str(payload)


def test_url_appears_once_revealed(session, no_cherrypy_session):
    reveal = _reveal(session, reveal_at=datetime.now(UTC) - timedelta(minutes=1))
    attendee = _eligible_attendee(session)
    session.add(WaitlistRevealLink(waitlist_reveal_id=reveal.id,
                                   attendee_id=attendee.id, token='tok'))
    session.flush()

    payload = _Payload(session).get('tok')
    assert payload['is_revealed'] is True
    assert payload['external_url'] == 'https://book.example.com/secret'


def test_a_shared_token_resolves(session, no_cherrypy_session):
    reveal = _reveal(session, reveal_at=datetime.now(UTC) - timedelta(minutes=1),
                     use_unique_links=False, shared_token='shared-abc')
    session.flush()

    payload = _Payload(session).get('shared-abc')
    assert payload['is_revealed'] is True
    assert payload['external_url'] == 'https://book.example.com/secret'


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
    session.add(WaitlistRevealLink(waitlist_reveal_id=reveal.id,
                                   attendee_id=attendee.id, token='tok-inactive'))
    session.flush()

    assert _Payload(session).get('tok-inactive')['error'] == 'inactive'
