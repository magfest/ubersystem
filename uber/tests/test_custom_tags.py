import pytest

from uber.common import *
from uber.custom_tags import (jsonize, linebreaksbr, datetime_local_filter,
    datetime_filter, full_datetime_local, hour_day_local, time_day_local,
    timedelta_filter, timestamp)


class TestDatetimeFilters(object):

    @pytest.mark.parametrize('filter_function', [
        datetime_local_filter,
        datetime_filter,
        full_datetime_local,
        hour_day_local,
        time_day_local,
        timestamp
    ])
    @pytest.mark.parametrize('test_input,expected', [
        (None, ''),
        ('', ''),
        ([], ''),
        ({}, '')
    ])
    def test_filters_allow_empty_arg(self, filter_function, test_input, expected):
        assert expected == filter_function(test_input)

    @pytest.mark.parametrize('timedelta_args,timedelta_kwargs', [
        ([], {}),
        ([], dict(days=1, seconds=30, microseconds=100, milliseconds=100, minutes=20, hours=12, weeks=2)),
        ([1, 30, 100, 100, 20, 12, 2], {}),
    ])
    def test_timedelta_filter(self, timedelta_args, timedelta_kwargs):
        dt = datetime.utcnow()
        td = timedelta(*timedelta_args, **timedelta_kwargs)
        expected = dt + td
        assert expected == timedelta_filter(dt, *timedelta_args, **timedelta_kwargs)

    def test_timedelta_filter_with_empty_date(self):
        assert timedelta_filter(dt=None, days=1, seconds=3600) is None
        assert timedelta_filter(dt='', days=1, seconds=3600) is None
        assert timedelta_filter(None, 1, 3600) is None
        assert timedelta_filter('', 1, 3600) is None

    def test_timedelta_filter_in_template(self):
        dt = datetime.utcnow()
        env = JinjaEnv.env()
        template = env.from_string('{{ dt|timedelta(days=-5)|datetime("%A, %B %-e") }}')
        expected = (dt + timedelta(days=-5)).strftime("%A, %B %-e")
        assert expected == template.render(dt=dt)

    def test_timedelta_filter_in_template_with_empty_date(self):
        env = JinjaEnv.env()
        template = env.from_string('{{ dt|timedelta(days=-5)|datetime("%A, %B %-e") }}')
        expected = ''
        assert expected == template.render(dt=None)


class TestJsonize(object):

    @pytest.mark.parametrize('test_input,expected', [
        (None, '{}'),
        ('', '""'),
        ('asdf', '"asdf"'),
        ({}, '{}'),
        ([], '[]'),
        (True, 'true'),
        (False, 'false'),
        (jinja2.runtime.Undefined(), '{}'),
    ])
    def test_jsonize(self, test_input, expected):
        assert expected == jsonize(test_input)


class TestLinebreaksbr(object):

    @pytest.mark.parametrize('test_input,expected', [
        ('', Markup('')),
        (Markup(''), Markup('')),
        ('asdf', Markup('asdf')),
        (Markup('asdf'), Markup('asdf')),
        ('asdf\nasdf', Markup('asdf<br />asdf')),
        (Markup('asdf\nasdf'), Markup('asdf<br />asdf')),
        ('asdf\r\nasdf', Markup('asdf<br />asdf')),
        ('asdf\rasdf', Markup('asdf<br />asdf')),
        ('asdf<br />asdf', Markup('asdf&lt;br /&gt;asdf')),
        ('asdf<br />asdf\nasdf', Markup('asdf&lt;br /&gt;asdf<br />asdf')),
        (Markup('asdf<br />asdf'), Markup('asdf<br />asdf')),
        (Markup('asdf<br />asdf\nasdf'), Markup('asdf<br />asdf<br />asdf'))
    ])
    def test_linebreaksbr(self, test_input, expected):
        assert expected == linebreaksbr(test_input)
