from datetime import datetime, date

import pytest
from pytz import UTC

from uber.config import c
from uber.models import Attendee, Session
from uber.site_sections import summary


@pytest.fixture
def birthdays():
    dates = [
        date(1964, 12, 30),
        date(1964, 12, 31),
        date(1964, 1, 1),
        date(1964, 1, 2),
        date(1964, 1, 9),
        date(1964, 1, 10),
        date(1964, 1, 11),
        date(1964, 1, 12),
        date(1964, 1, 30),
        date(1964, 1, 31),
        date(1964, 2, 1),
        date(1964, 2, 2),
        date(1964, 2, 27),
        date(1964, 2, 28),
        date(1964, 2, 29),
        date(1964, 3, 1),
        date(1964, 3, 2)]

    attendees = []
    for d in dates:
        attendees.append(Attendee(
            placeholder=True,
            first_name='Born on',
            last_name=d.strftime('%B %-d, %Y'),
            ribbon=c.VOLUNTEER_RIBBON,
            staffing=True,
            birthdate=d))

    ids = []
    with Session() as session:
        session.bulk_insert(attendees)
        ids = [a.id for a in attendees]

    yield ids

    with Session() as session:
        session.query(Attendee).filter(Attendee.id.in_(ids)).delete(
            synchronize_session=False)


class TestBirthdayCalendar(object):

    @pytest.mark.parametrize('year', [None, 2027, 2028])
    def test_attendee_birthday_calendar(
            self,
            admin_attendee,
            year,
            birthdays,
            monkeypatch):

        if year:
            assert str(year)
            response = summary.Root().attendee_birthday_calendar(year=year)
        else:
            assert str(datetime.now(UTC).year)
            response = summary.Root().attendee_birthday_calendar()
        if isinstance(response, bytes):
            response = response.decode('utf-8')

        lines = response.strip().split('\n')
        assert len(lines) == (17 + 1)  # Extra line for the header

    @pytest.mark.parametrize('epoch,eschaton,expected', [
        (datetime(2018, 1, 10), datetime(2018, 1, 11), 2),  # Normal dates
        (datetime(2017, 12, 31), datetime(2018, 1, 1), 2),  # Crossing the year
        (datetime(2018, 1, 31), datetime(2018, 2, 1), 2),  # Crossing the month
        (datetime(2018, 2, 28), datetime(2018, 3, 1), 3),  # Leap day
        (datetime(2018, 1, 1), datetime(2018, 3, 4), 15),  # Multi-month
        (datetime(2017, 12, 28), datetime(2018, 3, 4), 17),  # Everybody
    ])
    def test_event_birthday_calendar(
            self,
            admin_attendee,
            epoch,
            eschaton,
            expected,
            birthdays,
            monkeypatch):

        monkeypatch.setattr(c, 'EPOCH', epoch)
        monkeypatch.setattr(c, 'ESCHATON', eschaton)

        response = summary.Root().event_birthday_calendar()
        if isinstance(response, bytes):
            response = response.decode('utf-8')

        lines = response.strip().split('\n')
        assert len(lines) == (expected + 1)  # Extra line for the header

    def test_event_birthday_calendar_correct_birthday_years(
            self,
            admin_attendee,
            birthdays,
            monkeypatch):

        monkeypatch.setattr(c, 'EPOCH', datetime(2017, 12, 31))
        monkeypatch.setattr(c, 'ESCHATON', datetime(2018, 1, 1))

        response = summary.Root().event_birthday_calendar()
        if isinstance(response, bytes):
            response = response.decode('utf-8')

        assert '"Born on December 31, 1964\'s Birthday",2017-12-31' in response
        assert '"Born on January 1, 1964\'s Birthday",2018-01-01' in response

        lines = response.strip().split('\n')
        assert len(lines) == (2 + 1)  # Extra line for the header
