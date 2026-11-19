from datetime import datetime, timedelta

import pytest
from pytz import UTC

from uber.config import c
from uber.models import BadgeWaitlistSignup, Session


@pytest.fixture(autouse=True)
def empty_waitlist():
    # Positions rank against every signup of a badge type, so rows left by another
    # test would shift the expected numbers.
    with Session() as session:
        session.query(BadgeWaitlistSignup).delete()
        session.commit()
    yield
    with Session() as session:
        session.query(BadgeWaitlistSignup).delete()
        session.commit()


def _add_signups(session, badge_type, states):
    """Commit one signup per state, in queue order starting at queue number 1."""
    signups = []
    for number, state in enumerate(states, start=1):
        signup = BadgeWaitlistSignup(waitlist_type=badge_type, waitlist_position=number, first_name=f'Signup{number}',
                                     signup_time=datetime.now(UTC) - timedelta(hours=len(states) - number))
        if state == 'offered':
            signup.offered_badge = datetime.now(UTC)
        elif state in ('cancelled', 'removed', 'expired'):
            signup.status = {'cancelled': c.CANCELLED, 'removed': c.REMOVED, 'expired': c.EXPIRED}[state]
            signup.offered_badge = datetime.now(UTC) if state == 'expired' else None
        signups.append(signup)
    session.add_all(signups)
    session.commit()
    return signups


def test_positions_count_only_signups_still_waiting_ahead():
    # Signups that left the queue behind a signup must not lower its position.
    with Session() as session:
        signups = _add_signups(session, c.ATTENDEE_BADGE,
                               ['waiting', 'offered', 'waiting', 'cancelled', 'removed', 'expired', 'waiting'])
        positions = BadgeWaitlistSignup.current_positions(session, signups)

        assert positions == {signups[0].id: 1, signups[2].id: 2, signups[6].id: 3}


def test_cancellation_behind_a_signup_does_not_move_it_forward():
    with Session() as session:
        person_a, person_b, person_c = _add_signups(session, c.ATTENDEE_BADGE, ['waiting', 'waiting', 'waiting'])
        person_b.status = c.CANCELLED
        session.commit()

        assert person_a.current_waitlist_position == 1
        assert person_c.current_waitlist_position == 2


def test_badge_types_rank_separately():
    with Session() as session:
        adults = _add_signups(session, c.ATTENDEE_BADGE, ['offered', 'waiting'])
        children = _add_signups(session, c.CHILD_BADGE, ['waiting', 'waiting'])
        positions = BadgeWaitlistSignup.current_positions(session, adults + children)

        assert positions == {adults[1].id: 1, children[0].id: 1, children[1].id: 2}


def test_signup_without_a_queue_number_has_no_position():
    with Session() as session:
        signup = _add_signups(session, c.ATTENDEE_BADGE, ['waiting'])[0]
        signup.waitlist_position = 0
        session.commit()

        assert BadgeWaitlistSignup.current_positions(session, [signup]) == {}
        assert signup.current_waitlist_position is None


def test_current_waitlist_position_matches_the_bulk_lookup():
    with Session() as session:
        signups = _add_signups(session, c.ATTENDEE_BADGE, ['waiting', 'offered', 'cancelled', 'waiting'])

        assert signups[3].current_waitlist_position == 2
        assert signups[1].current_waitlist_position is None


def test_account_positions_cover_its_pending_signups():
    with Session() as session:
        account = session.create_attendee_account('waitlist-positions@mailinator.com')
        others = _add_signups(session, c.ATTENDEE_BADGE, ['offered', 'waiting', 'cancelled'])
        mine = BadgeWaitlistSignup(waitlist_type=c.ATTENDEE_BADGE, waitlist_position=4, attendee_account=account)
        session.add(mine)
        session.commit()

        assert account.pending_waitlist_signups_positions == {mine: 2}
        assert others[1].current_waitlist_position == 1

        session.delete(mine)
        session.delete(account)
        session.commit()


def test_displayed_position_is_the_current_position(monkeypatch):
    # The attendee homepage, cancel dialog and confirmation email show waitlist_position_trunc.
    monkeypatch.setattr(c, 'WAITLIST_MAX_POSITION', 0)
    with Session() as session:
        signups = _add_signups(session, c.ATTENDEE_BADGE, ['cancelled', 'waiting', 'waiting'])

        assert [signup.waitlist_position_trunc() for signup in signups[1:]] == [1, 2]


def test_displayed_position_is_capped_at_the_configured_maximum(monkeypatch):
    monkeypatch.setattr(c, 'WAITLIST_MAX_POSITION', 2)
    with Session() as session:
        signups = _add_signups(session, c.ATTENDEE_BADGE, ['waiting', 'waiting', 'waiting'])

        assert [signup.waitlist_position_trunc() for signup in signups] == [1, 2, '2+']
