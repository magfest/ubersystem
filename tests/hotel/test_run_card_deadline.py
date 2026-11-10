"""
Saving a lottery run's card deadline must store the typed event-local
time exactly: attaching a pytz zone with replace(tzinfo=) picks the zone's
LMT offset, so each save drifted the stored instant by a few minutes.
"""
from datetime import datetime
from urllib.parse import unquote

import cherrypy
import pytest

from uber.config import c
from uber.errors import HTTPRedirect
from uber.models.hotel import LotteryRun

from tests.hotel.factories import make_run


@pytest.fixture
def post_deadline(monkeypatch, session, no_cherrypy_session):
    import uber.site_sections.hotel_lottery_admin as admin

    monkeypatch.setattr(cherrypy.request, 'method', 'POST')
    monkeypatch.setattr(admin, 'check_csrf', lambda *a, **k: None)
    monkeypatch.setattr(session, 'commit', session.flush)

    def post(run, text):
        handler = admin.Root.update_run_card_deadline
        while hasattr(handler, '__wrapped__'):
            handler = handler.__wrapped__
        with pytest.raises(HTTPRedirect) as excinfo:
            handler(admin.Root(), session, id=run.id, card_deadline=text)
        session.expire_all()
        return unquote(excinfo.value.urls[0])
    return post


def test_deadline_is_stored_in_event_time(session, post_deadline):
    run = make_run(session, status=c.LOTTERY_PENDING)
    assert 'updated' in post_deadline(run, '2026-12-20 23:59')
    stored = session.get(LotteryRun, run.id).card_deadline
    assert stored == c.EVENT_TIMEZONE.localize(datetime(2026, 12, 20, 23, 59))
    assert stored.astimezone(c.EVENT_TIMEZONE).strftime('%Y-%m-%d %H:%M') == '2026-12-20 23:59'


def test_resaving_the_rendered_value_does_not_drift(session, post_deadline):
    run = make_run(session, status=c.LOTTERY_PENDING)
    post_deadline(run, '2026-12-20 23:59')
    first = session.get(LotteryRun, run.id).card_deadline
    # The edit form re-renders the stored value in event time; saving it
    # again unchanged must be a no-op.
    post_deadline(run, first.astimezone(c.EVENT_TIMEZONE).strftime('%Y-%m-%d %H:%M'))
    assert session.get(LotteryRun, run.id).card_deadline == first
