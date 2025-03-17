import pytest

from uber.config import c
from uber.models import Attendee, HotelRequests
from uber.utils import localized_now


def test_hotel_shifts_required(monkeypatch):
    monkeypatch.setattr(c, 'SHIFTS_CREATED', localized_now())
    assert not Attendee().hotel_shifts_required
    monkeypatch.setattr(Attendee, 'takes_shifts', True)
    monkeypatch.setattr(Attendee, 'hotel_nights', [c.THURSDAY, c.FRIDAY])
    assert Attendee().hotel_shifts_required
    monkeypatch.setattr(Attendee, 'is_dept_head', True)
    assert not Attendee().hotel_shifts_required


def test_hotel_shifts_required_preshifts(monkeypatch):
    monkeypatch.setattr(c, 'SHIFTS_CREATED', '')
    monkeypatch.setattr(Attendee, 'takes_shifts', True)
    monkeypatch.setattr(Attendee, 'hotel_nights', [c.THURSDAY, c.FRIDAY])
    assert not Attendee().hotel_shifts_required


@pytest.mark.parametrize('first,last,legal,expected', [
    ('First', 'Last', None, 'Last'),
    ('First', 'Last', 'First Last', 'Last'),
    ('First', 'Last', 'First Middle Last', 'Last'),
    ('CRAZY', 'Last', 'First Last', 'Last'),
    ('CRAZY', 'CRAZY', 'First Last', 'Last'),
    ('CRAZY', 'CRAZY', 'First Middle Last', 'Middle Last'),
    ('Bob', 'Brökken', 'Robert T. Brökken, M.D.', 'Brökken, M.D.'),
    ('Bob', 'Brökken', 'Robert T. Brökken,M.D.', 'Brökken,M.D.'),
    ('Bob', 'Brökken', 'Robert T. BrökkenMD', 'BrökkenMD'),
    ('Buster', 'Bluth', '  Byron  James  Bluth  III  Esq. ', 'Bluth III Esq.'),
    ('Buster', 'Bluth', 'Byron James Bluth,III,Esq.', 'Bluth,III,Esq.'),
])
def test_legal_last_name(first, last, legal, expected):
    assert expected == Attendee(first_name=first, last_name=last, legal_name=legal).legal_last_name


@pytest.mark.parametrize('first,last,legal,expected', [
    ('First', 'Last', None, 'First'),
    ('First', 'Last', 'First Last', 'First'),
    ('First', 'Last', 'First Middle Last', 'First Middle'),
    ('CRAZY', 'Last', 'First Last', 'First'),
    ('CRAZY', 'CRAZY', 'First Last', 'First'),
    ('CRAZY', 'CRAZY', 'First Middle Last', 'First'),
    ('Bob', 'Brökken', 'Robert T. Brökken, M.D.', 'Robert T.'),
    ('Bob', 'Brökken', 'Robert T. Brökken,M.D.', 'Robert T.'),
    ('Bob', 'Brökken', 'Robert T. BrökkenMD', 'Robert T.'),
    ('Buster', 'Bluth', '  Byron  James  Bluth  III  Esq. ', 'Byron James'),
    ('Buster', 'Bluth', 'Byron James Bluth,III,Esq.', 'Byron James'),
])
def test_legal_first_name(first, last, legal, expected):
    assert expected == Attendee(first_name=first, last_name=last, legal_name=legal).legal_first_name


class TestHotelRequests:

    @pytest.fixture(autouse=True)
    def hotel_request_unapproved_setup_teardown(self):
        # create an Attendee and HotelRequest for nights before and after the event, but don't approve the request yet
        hr = HotelRequests()
        hr.nights = ','.join(map(str, [c.WEDNESDAY, c.THURSDAY, c.MONDAY]))
        hr.attendee = Attendee()
        hr.presave_adjustments()
        return hr

    @pytest.fixture(autouse=True)
    def hotel_request_and_approve_setup_teardown(self, hotel_request_unapproved_setup_teardown):
        # create an Attendee and HotelRequest for nights before and after the event, and approve the request.
        hotel_request_unapproved_setup_teardown.approved = True
        hotel_request_unapproved_setup_teardown.presave_adjustments()
        return hotel_request_unapproved_setup_teardown

    def test_by_default_no_setup_and_teardown(self):
        attendee = Attendee()
        attendee.presave_adjustments()
        assert not attendee.can_work_setup
        assert not attendee.can_work_teardown

    def test_decline_setup_and_teardown(self, hotel_request_and_approve_setup_teardown):
        """
        if someone has previously been approved for their setup/teardown hotel request,
        then later declines it, we still allow them to sign up for setup/teardown shifts
        "If someone ends up being approved for setup nights and then declines their hotel space, it might just mean
        that they decided to room with a friend or something. Allowing them to still take setup shifts seems
        reasonable in that case." see https://github.com/magfest/hotel/issues/18
        """
        assert hotel_request_and_approve_setup_teardown.attendee.can_work_setup
        assert hotel_request_and_approve_setup_teardown.attendee.can_work_teardown

        hotel_request_and_approve_setup_teardown.decline()
        assert hotel_request_and_approve_setup_teardown.attendee.can_work_setup
        assert hotel_request_and_approve_setup_teardown.attendee.can_work_teardown

    def test_hotel_approved_and_can_work_setup_and_teardown(self, hotel_request_and_approve_setup_teardown):
        assert hotel_request_and_approve_setup_teardown.attendee.can_work_setup
        assert hotel_request_and_approve_setup_teardown.attendee.can_work_teardown
