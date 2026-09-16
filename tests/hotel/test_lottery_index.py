"""The lottery applications list (hotel_lottery_admin.index) always lands
on a page: no page param, page=0, or garbage all mean the first page."""

import pytest

from tests.hotel.factories import make_application, make_attendee


def _index(session, **kwargs):
    from uber.site_sections.hotel_lottery_admin import Root
    func = Root.index
    while hasattr(func, '__wrapped__'):
        func = func.__wrapped__
    return func(Root(), session, **kwargs)


@pytest.mark.parametrize('page', [None, '', '0', '-3', 'junk'])
def test_index_defaults_to_the_first_page(session, page):
    app = make_application(session, make_attendee(session))

    ctx = _index(session, **({} if page is None else {'page': page}))

    assert ctx['page'] == 1
    assert app in ctx['applications'], 'the first page lists applications'


def test_index_links_carry_search_and_filters(session):
    ctx = _index(session, filter_staff='true', filter_status='',
                 search_text='a b', page='1')
    assert ctx['advanced_filters'] == {'filter_staff': 'true'}
    assert ctx['list_qs'] == 'search_text=a+b&filter_staff=true'
