"""Badge transfers for attendees listed as an occupant of someone else's room."""
import copy

from uber.config import c
from uber.hotel.config import HotelLotteryConfig, hotel_lottery_config

from tests.hotel.factories import make_assignment, make_attendee, make_hotel, make_inventory


def _occupant_of(session, status=c.ASSIGNED):
    booker = make_attendee(session, 'Bea', 'Booker')
    occupant = make_attendee(session, 'Otis', 'Occupant')
    ra = make_assignment(session, booker, make_inventory(session, make_hotel(session)), status=status)
    ra.occupants.append(occupant)
    session.flush()
    session.expire(occupant, ['occupied_rooms'])
    return occupant


def test_attendee_without_a_room_can_transfer(session):
    assert make_attendee(session).is_inherently_transferable


def test_occupant_of_a_live_room_cannot_transfer(session):
    occupant = _occupant_of(session)

    assert not occupant.is_inherently_transferable
    assert not occupant.is_transferable
    assert 'cancel or leave your hotel room' in occupant.transferable_actions


def test_occupant_of_a_locked_room_is_sent_to_the_hotel_team(session, monkeypatch):
    monkeypatch.setattr(c, 'HOTEL_LOTTERY_EMAIL', 'Hotel Team <hotel@example.com>')
    occupant = _occupant_of(session)
    settings = copy.deepcopy(HotelLotteryConfig.defaults)
    settings['room_changes_locked'] = True
    hotel_lottery_config.save(settings, session)

    assert not occupant.is_inherently_transferable
    assert occupant.transferable_actions == ['contact hotel@example.com to be removed from your hotel room']


def test_occupant_of_a_cancelled_room_can_transfer(session):
    assert _occupant_of(session, status=c.CANCELLED).is_inherently_transferable


def test_admin_override_lets_an_occupant_transfer(session):
    occupant = _occupant_of(session)
    assert not occupant.cannot_transfer_reason
    occupant.can_transfer = True

    assert occupant.is_transferable
