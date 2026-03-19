from datetime import datetime, timedelta

import jinja2
import pytest
from markupsafe import Markup

from uber.custom_tags import jsonize, linebreaksbr, datetime_local_filter, datetime_filter, full_datetime_local, \
    hour_day_local, time_day_local, timedelta_filter, timestamp, url_to_link, basename, form_link, humanize_timedelta
from uber.jinja import JinjaEnv
from uber.models import WatchList


class TestDatetimeFilters(object):

    @pytest.mark.parametrize('filter_function', [
        datetime_local_filter,
        datetime_filter,
        full_datetime_local,
        hour_day_local,
        time_day_local,
        timestamp,
        basename
    ])
    @pytest.mark.parametrize('test_input,expected', [
        (None, ''),
        ('', ''),
        ([], ''),
        ({}, ''),
        (jinja2.runtime.Undefined(), '')
    ])
    def test_filters_allow_empty_arg(self, filter_function, test_input, expected):
        assert expected == filter_function(test_input)

    @pytest.mark.parametrize('timedelta_args,timedelta_kwargs', [
        ([], {}),
        ([], dict(days=1, seconds=30, microseconds=100, milliseconds=100, minutes=20, hours=12, weeks=2)),
        ([1, 30, 100, 100, 20, 12, 2], {}),
    ])
    def test_timedelta_filter(self, timedelta_args, timedelta_kwargs):
        dt = datetime.now(UTC)
        td = timedelta(*timedelta_args, **timedelta_kwargs)
        expected = dt + td
        assert expected == timedelta_filter(dt, *timedelta_args, **timedelta_kwargs)

    def test_timedelta_filter_with_empty_date(self):
        assert timedelta_filter(dt=None, days=1, seconds=3600) is None
        assert timedelta_filter(dt='', days=1, seconds=3600) is None
        assert timedelta_filter(None, 1, 3600) is None
        assert timedelta_filter('', 1, 3600) is None

    def test_timedelta_filter_in_template(self):
        dt = datetime.now(UTC)
        env = JinjaEnv.env()
        template = env.from_string('{{ dt|timedelta(days=-5)|datetime("%A, %B %-e") }}')
        expected = (dt + timedelta(days=-5)).strftime("%A, %B %-e")
        assert expected == template.render(dt=dt)

    def test_timedelta_filter_in_template_with_empty_date(self):
        env = JinjaEnv.env()
        template = env.from_string('{{ dt|timedelta(days=-5)|datetime("%A, %B %-e") }}')
        expected = ''
        assert expected == template.render(dt=None)


@pytest.mark.parametrize('first_names,last_name,expected', [
    ('', '', 'Unknown'),
    ('', 'Last', 'Last'),
    ('First', '', 'First'),
    ('First', 'Last', 'First Last'),
    ('First, Second', 'Last', 'First, Second Last'),
    ('First, Second, Third', 'Last', 'First, Second, Third Last'),
])
def test_watch_list(first_names, last_name, expected):
    assert form_link(WatchList(first_names=first_names, last_name=last_name)) == expected


class TestHumanizeTimedelta(object):

    @pytest.mark.parametrize('test_args,test_kwargs,expected', [
        ([], {}, 'right now'),
        ([None], {}, 'right now'),
        ([0], {}, 'right now'),
        ([''], {}, 'right now'),
        ([jinja2.runtime.Undefined()], {}, 'right now'),
        ([timedelta()], {}, 'right now'),
        ([], {'years': 0}, 'right now'),
        ([], {'months': 0}, 'right now'),
        ([], {'days': 0}, 'right now'),
        ([], {'hours': 0}, 'right now'),
        ([], {'minutes': 0}, 'right now'),
        ([], {'seconds': 0}, 'right now'),
        ([], {'years': 1}, '1 year'),
        ([], {'months': 1}, '1 month'),
        ([], {'days': 1}, '1 day'),
        ([], {'hours': 1}, '1 hour'),
        ([], {'minutes': 1}, '1 minute'),
        ([], {'seconds': 1}, '1 second'),
        ([], {'years': 2}, '2 years'),
        ([], {'months': 2}, '2 months'),
        ([], {'days': 2}, '2 days'),
        ([], {'hours': 2}, '2 hours'),
        ([], {'minutes': 2}, '2 minutes'),
        ([], {'seconds': 2}, '2 seconds'),
        ([], {'months': 23}, '1 year and 11 months'),
        ([], {'hours': 28}, '1 day and 4 hours'),
        ([], {'minutes': 69}, '1 hour and 9 minutes'),
        ([], {'seconds': 4163}, '1 hour, 9 minutes, and 23 seconds'),
        ([], {'seconds': 4163, 'granularity': 'minutes'}, '1 hour and 9 minutes'),
    ])
    def test_humanize_timedelta(self, test_args, test_kwargs, expected):
        assert expected == humanize_timedelta(*test_args, **test_kwargs)


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


class TestUrlToLink(object):

    @pytest.mark.parametrize('url_args, url_kwargs, expected', [
        ([''], {}, ''),
        (['/regular/url'], {}, '<a href="/regular/url">/regular/url</a>'),
        (['/regular/url', 'normaltext'], {}, '<a href="/regular/url">normaltext</a>'),
        (['/regular/url', 'normaltext', '_blank'], {}, '<a href="/regular/url" target="_blank">normaltext</a>'),
        (['&<>"\'', 'normaltext'], {}, '<a href="&amp;&lt;&gt;&#34;&#39;">normaltext</a>'),
        (['/regular/url', '&<>"\''], {}, '<a href="/regular/url">&amp;&lt;&gt;&#34;&#39;</a>'),
        (
            ['/regular/url', 'normaltext', '&<>"\''],
            {},
            '<a href="/regular/url" target="&amp;&lt;&gt;&#34;&#39;">normaltext</a>'
        ),
    ])
    def test_urltolink(self, url_args, url_kwargs, expected):
        assert expected == url_to_link(*url_args, **url_kwargs)
