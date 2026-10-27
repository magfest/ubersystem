"""The partition card deadline, set in the Partition Rooms section of Lottery
Settings.

It lives in the hotel_lottery database settings, not the config file, so Hotel
Dept can change it without a deploy. A date means 11:59pm event time. It is
shown in emails only; nothing expires on it.
"""

import copy
from datetime import datetime
from urllib.parse import unquote

import cherrypy
import pytest

from uber.config import c
from uber.errors import HTTPRedirect
from uber.hotel.config import HotelLotteryConfig, hotel_lottery_config

from tests.hotel.test_partition_room_emails import _grant, partition_fixtures  # noqa: F401


def set_partition_guarantee_due(session, value):
    data = copy.deepcopy(HotelLotteryConfig.defaults)
    data['partition_guarantee_due'] = value
    hotel_lottery_config.save(data, session)


@pytest.fixture
def post_settings(monkeypatch, session, no_cherrypy_session):
    import uber.site_sections.hotel_lottery_admin as admin

    monkeypatch.setattr(cherrypy.request, 'method', 'POST')
    monkeypatch.setattr(admin, 'check_csrf', lambda *a, **k: None)
    monkeypatch.setattr(session, 'commit', session.flush)

    def post(handler_name, **params):
        handler = getattr(admin.Root, handler_name)
        while hasattr(handler, '__wrapped__'):
            handler = handler.__wrapped__
        with pytest.raises(HTTPRedirect) as excinfo:
            handler(admin.Root(), session, **params)
        return unquote(excinfo.value.urls[0])
    return post


@pytest.fixture
def save_settings(post_settings):
    return lambda **params: post_settings('update_partition_settings', **params)


def test_deadline_is_unset_by_default(session):
    assert hotel_lottery_config.load(session).partition_guarantee_due is None


def test_settings_page_saves_a_date_as_end_of_day(session, save_settings):
    assert 'saved' in save_settings(partition_guarantee_due='2026-11-22')
    assert hotel_lottery_config.load(session).partition_guarantee_due == \
        c.EVENT_TIMEZONE.localize(datetime(2026, 11, 22, 23, 59))


def test_settings_page_clears_the_date(session, save_settings):
    set_partition_guarantee_due(session, '2026-11-22')
    save_settings(partition_guarantee_due='')
    assert hotel_lottery_config.load(session).partition_guarantee_due is None


def test_settings_page_rejects_a_bad_date(session, save_settings):
    set_partition_guarantee_due(session, '2026-11-22')
    assert 'Could not parse' in save_settings(partition_guarantee_due='Nov 22')
    assert hotel_lottery_config.load(session).partition_guarantee_due is not None


def test_saving_lottery_status_keeps_the_deadline(session, post_settings):
    set_partition_guarantee_due(session, '2026-11-22')
    post_settings('update_lottery_settings', room_changes_locked='1')
    settings = hotel_lottery_config.load(session)
    assert settings.room_changes_locked
    assert settings.partition_guarantee_due is not None


def test_saving_the_deadline_keeps_lottery_status(session, post_settings):
    post_settings('update_lottery_settings', room_changes_locked='1')
    post_settings('update_partition_settings', partition_guarantee_due='2026-11-22')
    assert hotel_lottery_config.load(session).room_changes_locked


def test_room_reads_the_deadline(session, partition_fixtures):  # noqa: F811
    ra = _grant(session)
    assert ra.partition_guarantee_due is None
    set_partition_guarantee_due(session, '2026-11-22')
    assert ra.partition_guarantee_due.date().isoformat() == '2026-11-22'
