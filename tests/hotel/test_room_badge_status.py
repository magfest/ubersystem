"""Only badges in a state that can hold a hotel room are offered by the room
pickers or accepted by the paths that put someone in a room."""

from datetime import timedelta

import cherrypy
import pytest
import sqlalchemy as sa

from uber.config import c
from uber.errors import HTTPRedirect
from uber.models import Attendee

from tests.hotel.factories import (N, make_assignment, make_attendee, make_attendee_account,
                                   make_hotel, make_inventory, make_partition, make_partition_block)

BLOCKED = ['PENDING_STATUS', 'INVALID_STATUS', 'IMPORTED_STATUS', 'INVALID_GROUP_STATUS', 'REFUNDED_STATUS',
           'WAITLIST_REFUND_STATUS', 'NOT_ATTENDING', 'DEFERRED_STATUS', 'WATCHED_STATUS']
ALLOWED = ['NEW_STATUS', 'COMPLETED_STATUS', 'UNAPPROVED_DEALER_STATUS']


@pytest.fixture
def room(session):
    inv = make_inventory(session, make_hotel(session), capacity=4, quantity=5)
    partition = make_partition(session)
    make_partition_block(session, partition, inv, 5)
    return make_assignment(session, make_attendee(session), inventory=inv, partition_id=partition.id,
                           status=c.ASSIGNED, check_in=N[1], check_out=N[3])


def _badge(session, status, **overrides):
    """An attendee at this badge status. Written in SQL because presave
    adjustments move some statuses on, such as On Hold with no watchlist match."""
    attendee = make_attendee(session, **overrides)
    session.execute(sa.update(Attendee).where(Attendee.id == attendee.id).values(badge_status=getattr(c, status)))
    session.refresh(attendee)
    return attendee


def _in_sql(session, attendee, rule):
    return bool(session.query(Attendee.id).filter(Attendee.id == attendee.id, rule).count())


@pytest.mark.parametrize('status', BLOCKED + ALLOWED)
def test_python_and_sql_rules_agree(session, status):
    attendee = _badge(session, status)

    assert attendee.can_hold_hotel_room is (status in ALLOWED)
    assert _in_sql(session, attendee, Attendee.can_hold_hotel_room) is (status in ALLOWED)
    assert attendee.hotel_lottery_eligible is (status in ALLOWED)
    assert _in_sql(session, attendee, Attendee.hotel_lottery_eligible) is (status in ALLOWED)


def test_placeholders_can_hold_a_room_but_not_enter_the_lottery(session):
    attendee = make_attendee(session, placeholder=True)

    assert attendee.can_hold_hotel_room and _in_sql(session, attendee, Attendee.can_hold_hotel_room)
    assert not attendee.hotel_lottery_eligible
    assert not _in_sql(session, attendee, Attendee.hotel_lottery_eligible)


def test_unassigned_group_badges_cannot_hold_a_room(session):
    attendee = make_attendee(session)
    attendee.first_name = attendee.last_name = ''
    session.flush()

    assert not attendee.can_hold_hotel_room
    assert not _in_sql(session, attendee, Attendee.can_hold_hotel_room)


def test_picker_lists_only_badges_that_can_hold_a_room(session):
    from uber.hotel.queries import attendee_search_results

    good = make_attendee(session, last='Okonkwo-Bell')
    placeholder = make_attendee(session, last='Okonkwo-Bell', placeholder=True)
    for status in BLOCKED:
        _badge(session, status, last='Okonkwo-Bell')

    assert {row['id'] for row in attendee_search_results(session, 'Okonkwo-Bell')} == {good.id, placeholder.id}


@pytest.mark.parametrize('term', ['id', 'email'])
def test_picker_hides_a_blocked_badge_searched_by_id_or_email(session, term):
    from uber.hotel.queries import attendee_search_results

    refunded = make_attendee(session, badge_status=c.REFUNDED_STATUS)

    assert attendee_search_results(session, getattr(refunded, term)) == []


@pytest.mark.parametrize('status', BLOCKED)
def test_a_room_cannot_be_created_for_a_blocked_badge(session, room, status):
    from uber.hotel.service import RoomAssignmentError, create_room_assignment

    attendee = _badge(session, status)

    with pytest.raises(RoomAssignmentError) as error:
        create_room_assignment(session, attendee_id=attendee.id, inventory_id=room.inventory_id,
                               partition_id=room.partition_id)

    # Partition owners see this message, so it must not reveal a watchlist hold.
    assert attendee.badge_status_label not in error.value.message
    assert not attendee.room_assignments


def test_a_room_can_be_created_for_a_placeholder(session, room):
    from uber.hotel.service import create_room_assignment

    guest = make_attendee(session, placeholder=True)

    assert create_room_assignment(session, attendee_id=guest.id, inventory_id=room.inventory_id,
                                  partition_id=room.partition_id).attendee_id == guest.id


def test_a_blocked_badge_cannot_be_added_as_a_roommate(session, room):
    from uber.hotel.service import RoomAssignmentError, add_room_occupant

    attendee = make_attendee(session, badge_status=c.REFUNDED_STATUS)

    with pytest.raises(RoomAssignmentError):
        add_room_occupant(session, room, attendee.id)
    assert attendee not in room.occupants


def test_a_roommate_whose_badge_is_now_blocked_can_be_removed_but_not_made_leader(session, room):
    from uber.hotel.service import RoomAssignmentError, remove_room_occupant, set_room_leader

    roommate = make_attendee(session)
    room.occupants.append(roommate)
    session.flush()
    roommate.badge_status = c.REFUNDED_STATUS
    session.flush()

    with pytest.raises(RoomAssignmentError):
        set_room_leader(session, room, roommate.id)
    remove_room_occupant(session, room, roommate.id)

    assert roommate not in room.occupants


@pytest.fixture
def assign_room(session, post_request, monkeypatch):
    import uber.site_sections.hotel_lottery_admin as admin_site

    monkeypatch.setattr(admin_site, 'is_lottery_admin', lambda: True)
    monkeypatch.setattr(session, 'commit', session.flush)
    func = admin_site.Root.assign_room
    while hasattr(func, '__wrapped__'):
        func = func.__wrapped__

    def call(**kwargs):
        with pytest.raises(HTTPRedirect) as redirect:
            func(admin_site.Root(), session, **kwargs)
        return redirect.value.urls[0]
    return call


def test_an_existing_room_cannot_be_handed_to_a_blocked_badge(session, room, assign_room):
    booker, attendee = room.attendee_id, make_attendee(session, badge_status=c.DEFERRED_STATUS)

    url = assign_room(id=room.id, attendee_id=attendee.id, inventory_id=room.inventory_id,
                      partition_id=room.partition_id)

    assert 'hotel%20room' in url or 'hotel+room' in url
    assert room.attendee_id == booker


def test_a_room_already_held_by_a_blocked_badge_can_still_be_edited(session, room, assign_room):
    room.attendee.badge_status = c.REFUNDED_STATUS
    session.flush()

    url = assign_room(id=room.id, attendee_id=room.attendee_id, inventory_id=room.inventory_id,
                      partition_id=room.partition_id, admin_notes='Waiting on the hotel')

    assert 'saved' in url
    assert room.admin_notes == 'Waiting on the hotel'


@pytest.fixture
def attendee_page(session, post_request, monkeypatch):
    import uber.site_sections.hotel_lottery as site
    from uber.models import initialize_db

    initialize_db()
    monkeypatch.setattr(cherrypy, 'session', {}, raising=False)
    monkeypatch.setattr(c, 'HAS_HOTEL_LOTTERY_ADMIN_ACCESS', False, raising=False)
    monkeypatch.setattr(site, 'check_csrf', lambda *a, **k: None)
    monkeypatch.setattr(session, 'commit', session.flush)

    def call(name, account, **kwargs):
        monkeypatch.setattr(cherrypy.request, 'attendee_account', account.id, raising=False)
        monkeypatch.setattr(cherrypy.request, 'admin_account', None, raising=False)
        func = getattr(site.Root, name)
        while hasattr(func, '__wrapped__'):
            func = func.__wrapped__
        with pytest.raises(HTTPRedirect) as redirect:
            func(site.Root(), session, **kwargs)
        return redirect.value.urls[0]
    return call


def _invite(session, room):
    from uber.models.hotel import RoomAssignmentInvite

    invite = RoomAssignmentInvite(room_assignment_id=room.id, invite_token='DEMO-INVITE')
    session.add(invite)
    session.flush()
    return invite


def test_a_blocked_badge_cannot_accept_a_room_invite_and_the_invite_survives(session, room, attendee_page):
    from uber.models.hotel import RoomAssignmentInvite

    invite, attendee = _invite(session, room), make_attendee(session, badge_status=c.NOT_ATTENDING)

    attendee_page('invite', make_attendee_account(session, attendee), token='DEMO-INVITE', action='accept',
                  attendee_id=attendee.id)

    assert attendee not in room.occupants
    assert session.get(RoomAssignmentInvite, invite.id)


def test_a_blocked_badge_can_decline_a_room_invite(session, room, attendee_page):
    from uber.models.hotel import RoomAssignmentInvite

    invite, attendee = _invite(session, room), make_attendee(session, badge_status=c.NOT_ATTENDING)

    attendee_page('invite', make_attendee_account(session, attendee), token='DEMO-INVITE', action='reject',
                  attendee_id=attendee.id)

    assert session.get(RoomAssignmentInvite, invite.id) is None


def test_an_emailed_invite_skips_the_accounts_blocked_badge(session, room, attendee_page):
    _invite(session, room)
    refunded, good = make_attendee(session, badge_status=c.REFUNDED_STATUS), make_attendee(session)

    attendee_page('invite', make_attendee_account(session, refunded, good), token='DEMO-INVITE', action='accept')

    assert good in room.occupants
    assert refunded not in room.occupants


def test_copying_guests_skips_a_blocked_badge(session, room, attendee_page):
    other = make_assignment(session, room.attendee, inventory=room.inventory, partition_id=room.partition_id,
                            status=c.ASSIGNED, check_in=N[1], check_out=N[3])
    good, refunded = make_attendee(session), make_attendee(session, badge_status=c.REFUNDED_STATUS)
    other.occupants.extend([good, refunded])
    session.flush()

    attendee_page('copy_occupants', make_attendee_account(session, room.attendee), target_assignment_id=room.id,
                  attendee_id=room.attendee_id, source_attendee_ids=f'{good.id},{refunded.id}')

    assert good in room.occupants
    assert refunded not in room.occupants


def test_the_leader_cannot_hand_the_room_to_a_blocked_badge(session, room, attendee_page):
    booker, roommate = room.attendee, make_attendee(session, badge_status=c.REFUNDED_STATUS)
    room.occupants.append(roommate)
    session.flush()

    attendee_page('make_room_leader', make_attendee_account(session, booker), ra=room,
                  occupant_attendee_id=roommate.id)

    assert room.attendee_id == booker.id


def _roommate_past_deadline(session, room, **room_attrs):
    from datetime import timedelta
    from uber.utils import localized_now

    roommate = make_attendee(session)
    room.occupants.append(roommate)
    room.deposit_cutoff_date = localized_now().date() - timedelta(days=1)
    for attr, value in room_attrs.items():
        setattr(room, attr, value)
    session.flush()
    return roommate


def test_the_leader_cannot_be_changed_after_the_card_deadline(session, room):
    from uber.hotel.service import RoomAssignmentError, set_room_leader

    booker = room.attendee
    roommate = _roommate_past_deadline(session, room, status=c.SECURED, cc_token='tok')

    with pytest.raises(RoomAssignmentError):
        set_room_leader(session, room, roommate.id)

    assert (room.attendee_id, room.status, room.cc_token) == (booker.id, c.SECURED, 'tok')


def test_the_leader_can_be_changed_on_the_card_deadline_day(session, room):
    from uber.hotel.service import set_room_leader
    from uber.utils import localized_now

    roommate = _roommate_past_deadline(session, room, deposit_cutoff_date=localized_now().date())

    set_room_leader(session, room, roommate.id)

    assert room.attendee_id == roommate.id


def test_a_room_that_needs_no_card_can_change_leader_after_the_deadline(session, room):
    from uber.hotel.service import set_room_leader

    roommate = _roommate_past_deadline(session, room, payment_type='master_bill')
    assert not room.require_cc

    set_room_leader(session, room, roommate.id)

    assert room.attendee_id == roommate.id


def test_the_attendee_page_refuses_a_leader_change_after_the_card_deadline(session, room, attendee_page):
    booker = room.attendee
    roommate = _roommate_past_deadline(session, room, status=c.SECURED, cc_token='tok')

    url = attendee_page('make_room_leader', make_attendee_account(session, booker), ra=room,
                        occupant_attendee_id=roommate.id)

    assert 'deadline' in url
    assert (room.attendee_id, room.status, room.cc_token) == (booker.id, c.SECURED, 'tok')


def _two_days_out():
    from datetime import timedelta
    from uber.utils import localized_now

    return localized_now().date() + timedelta(days=2)


def test_an_admin_leader_change_after_the_deadline_extends_it_two_days(session, room):
    from uber.hotel.service import set_room_leader

    roommate = _roommate_past_deadline(session, room, status=c.SECURED, cc_token='tok')

    set_room_leader(session, room, roommate.id, extend_deadline=True)

    assert (room.attendee_id, room.status, room.cc_token) == (roommate.id, c.ASSIGNED, None)
    assert room.deposit_cutoff_date == _two_days_out()


def test_an_admin_leader_change_before_the_deadline_leaves_it_alone(session, room):
    from uber.hotel.service import set_room_leader

    deadline = _two_days_out() + timedelta(days=10)
    roommate = _roommate_past_deadline(session, room, deposit_cutoff_date=deadline)

    set_room_leader(session, room, roommate.id, extend_deadline=True)

    assert room.deposit_cutoff_date == deadline


def test_an_admin_on_the_attendee_page_extends_the_deadline(session, room, attendee_page, monkeypatch):
    booker = room.attendee
    roommate = _roommate_past_deadline(session, room, status=c.SECURED, cc_token='tok')
    monkeypatch.setattr(c, 'HAS_HOTEL_LOTTERY_ADMIN_ACCESS', True, raising=False)

    url = attendee_page('make_room_leader', make_attendee_account(session, booker), ra=room,
                        occupant_attendee_id=roommate.id)

    assert 'extended' in url
    assert (room.attendee_id, room.deposit_cutoff_date) == (roommate.id, _two_days_out())


def _leader_emails(session, room):
    from uber.models import Email

    session.flush()
    return session.query(Email).filter_by(fk_id=room.id, ident='hotel_room_leader_changed').all()


def test_the_new_leader_is_told_to_put_a_card_down(session, room, attendee_page, monkeypatch):
    booker = room.attendee
    roommate = _roommate_past_deadline(session, room, status=c.SECURED, cc_token='tok')
    monkeypatch.setattr(c, 'HAS_HOTEL_LOTTERY_ADMIN_ACCESS', True, raising=False)

    attendee_page('make_room_leader', make_attendee_account(session, booker), ra=room,
                  occupant_attendee_id=roommate.id)

    [email] = _leader_emails(session, room)
    assert email.to == roommate.email
    assert f'Hello {roommate.first_name}:' in email.body
    assert _two_days_out().strftime('%A, %B %-d') in email.body


def test_a_room_that_needs_no_card_sends_no_leader_email(session, room):
    from uber.hotel.service import set_room_leader

    roommate = _roommate_past_deadline(session, room, payment_type='master_bill')

    set_room_leader(session, room, roommate.id)

    assert _leader_emails(session, room) == []


def test_changing_the_leader_twice_leaves_one_unsent_email(session, room):
    from uber.hotel.service import set_room_leader

    booker = room.attendee
    roommate = make_attendee(session)
    room.occupants.append(roommate)
    session.flush()

    set_room_leader(session, room, roommate.id)
    set_room_leader(session, room, booker.id)

    [email] = _leader_emails(session, room)
    assert f'Hello {booker.first_name}:' in email.body


@pytest.fixture
def leader_email_enabled(session, monkeypatch):
    """The leader email set to Autosend, so the sweep and save checks consider it."""
    from uber.models import AutomatedEmail

    if not AutomatedEmail.initialized:
        AutomatedEmail.reconcile_fixtures()
        AutomatedEmail.initialized = True
    fixture = session.query(AutomatedEmail).filter_by(ident='hotel_room_leader_changed').one()
    fixture.policy = c.AUTOSEND
    session.flush()
    # The sweep commits; keep it inside the per-test rollback.
    monkeypatch.setattr(session, 'commit', session.flush)
    return fixture


def test_the_sweeps_never_generate_the_leader_email(session, room, leader_email_enabled):
    from uber.email import EmailService

    assert room.needs_card
    assert EmailService.check_emails_for_fixture(session, leader_email_enabled) == 0
    EmailService.check_emails_for_model(session, room)

    assert _leader_emails(session, room) == []


def test_the_save_check_does_not_copy_an_unflushed_leader_email(session, room, leader_email_enabled):
    from uber.email import EmailService
    from uber.hotel.service import queue_new_leader_email

    queue_new_leader_email(session, room)
    EmailService.check_emails_for_model(session, room)

    assert len(_leader_emails(session, room)) == 1


def test_a_leader_email_for_a_room_since_cancelled_is_deleted_at_send(session, room, leader_email_enabled):
    from uber.email import EmailService
    from uber.hotel.service import set_room_leader

    roommate = make_attendee(session)
    room.occupants.append(roommate)
    session.flush()
    set_room_leader(session, room, roommate.id)
    [email] = _leader_emails(session, room)

    room.status = c.CANCELLED
    session.flush()
    assert EmailService.send_email(session, email, to_model=room) is None
    assert _leader_emails(session, room) == []
