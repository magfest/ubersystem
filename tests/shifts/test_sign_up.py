import inspect
from datetime import timedelta

import pytest

from uber.config import c
from uber.models import Attendee, Session
from uber.site_sections.staffing import Root
from uber.utils import localized_now

# The undecorated handler body; the account and CSRF decorators need a live request.
sign_up = inspect.unwrap(Root.sign_up)


@pytest.fixture
def signups_open(monkeypatch):
    monkeypatch.setattr(c, 'SHIFTS_CREATED', localized_now() - timedelta(days=1))
    monkeypatch.setattr(c, 'VOLUNTEER_CHECKLIST_OPEN', '')


def _sign_up(committed):
    with Session() as session:
        return sign_up(Root(), session, id=committed['first'], job_id=committed['job'])


def test_sign_up_refused_before_signups_start(committed, shift_count, signups_open, monkeypatch):
    monkeypatch.setattr(c, 'SHIFTS_CREATED', localized_now() + timedelta(days=1))

    assert _sign_up(committed) == {'success': False, 'message': 'Shift signups are not available yet.'}
    assert shift_count(committed['job']) == 0


def test_non_staff_volunteer_waits_for_volunteer_signups_start(committed, shift_count, signups_open, monkeypatch):
    monkeypatch.setattr(c, 'VOLUNTEER_SIGNUPS_START', localized_now() + timedelta(days=1))
    with Session() as session:
        session.query(Attendee).filter(Attendee.id == committed['first']).update({'badge_type': c.ATTENDEE_BADGE})
        session.commit()

    assert _sign_up(committed) == {'success': False, 'message': 'Shift signups are not available yet.'}
    assert shift_count(committed['job']) == 0


def test_sign_up_refused_until_checklist_complete(committed, shift_count, signups_open, monkeypatch):
    monkeypatch.setattr(c, 'VOLUNTEER_CHECKLIST_OPEN', localized_now() - timedelta(days=1))

    result = _sign_up(committed)

    assert result['success'] is False
    assert result['message'] == 'Please complete your volunteer checklist before signing up for shifts.'
    assert shift_count(committed['job']) == 0


def test_sign_up_succeeds_when_open(committed, shift_count, signups_open):
    assert _sign_up(committed)['success'] is True
    assert shift_count(committed['job']) == 1
