"""Free-text search on the hotel lottery admin list pages: the
applications index (`_search`) and the rooms list
(`build_room_assignment_query`) both find attendees by name."""

import pytest

from uber.config import c
from uber.hotel.queries import build_room_assignment_query

from tests.hotel.factories import (N, make_application, make_assignment,
                                   make_attendee, make_hotel, make_inventory)


@pytest.fixture
def zelda(session):
    attendee = make_attendee(session, first='Zelda', last='Quartermain')
    attendee.hotel_first_name = 'Zee'
    attendee.hotel_last_name = 'Quill'
    session.flush()
    app = make_application(session, attendee, status=c.COMPLETE,
                           entry_type=c.ROOM_ENTRY,
                           admin_notes='needs a quiet floor')
    inv = make_inventory(session, make_hotel(session), quantity=2)
    ra = make_assignment(session, attendee, inv, status=c.ASSIGNED,
                         lottery_application_id=app.id,
                         check_in=N[1], check_out=N[3])
    return attendee, app, ra


def _app_search(session, text):
    from uber.site_sections.hotel_lottery_admin import _search
    query, message = _search(session, text)
    return query.all(), message


@pytest.mark.parametrize('text', [
    'Zelda', 'Quartermain', 'Zelda Quartermain', 'zelda quarter',
    'Zee Quill', 'quiet floor',
])
def test_applications_search_matches_names_and_notes(session, zelda, text):
    attendee, app, _ = zelda
    results, message = _app_search(session, text)
    assert app in results
    assert message == ''


def test_applications_search_ignores_other_attendees(session, zelda):
    _, app, _ = zelda
    other = make_application(session, make_attendee(session, first='Link', last='Hyrule'))
    results, _ = _app_search(session, 'Zelda Quartermain')
    assert app in results and other not in results
    results, _ = _app_search(session, 'Ganondorf')
    assert results == []


def test_applications_search_by_email(session, zelda):
    attendee, app, _ = zelda
    results, _ = _app_search(session, attendee.email)
    assert results == [app]


@pytest.mark.parametrize('text', ['Zelda', 'Quartermain', 'Zelda Quartermain', 'Zee Quill'])
def test_rooms_search_matches_full_name(session, zelda, text):
    _, _, ra = zelda
    rows = build_room_assignment_query(session, search=text).all()
    assert ra in rows


def test_rooms_search_excludes_non_matches(session, zelda):
    _, _, ra = zelda
    assert ra not in build_room_assignment_query(session, search='Ganondorf').all()
