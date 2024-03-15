import pytest

from uber.config import c
from uber.models import Attendee, HotelRequests, Session
from uber.utils import localized_now


def test_hotel_shifts_required(monkeypatch):
    monkeypatch.setattr(c, 'VOLUNTEER_CHECKLIST_OPEN', True)
    assert not Attendee().hotel_shifts_required
    monkeypatch.setattr(Attendee, 'takes_shifts', True)
    monkeypatch.setattr(Attendee, 'hotel_nights', [c.THURSDAY, c.FRIDAY])
    assert Attendee().hotel_shifts_required
    monkeypatch.setattr(Attendee, 'is_dept_head', True)
    assert not Attendee().hotel_shifts_required


def test_hotel_shifts_required_checklist_closed(monkeypatch):
    monkeypatch.setattr(c, 'VOLUNTEER_CHECKLIST_OPEN', False)
    monkeypatch.setattr(Attendee, 'takes_shifts', True)
    monkeypatch.setattr(Attendee, 'hotel_nights', [c.THURSDAY, c.FRIDAY])
    assert not Attendee().hotel_shifts_required


@pytest.mark.parametrize('first,last,legal,expected', [
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
    attendee = Attendee(first_name=first, last_name=last, legal_name=legal)
    assert expected == attendee.legal_last_name


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
