import pytest

from uber.common import *
from uber.custom_tags import (jsonize, linebreaksbr, datetime_local_filter,
    datetime_filter, full_datetime_local, hour_day_local, time_day_local, timestamp)


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


class TestJsonize(object):

    @pytest.mark.parametrize('test_input,expected', [
        (None, '{}'),
        ('', '""'),
        ('asdf', '"asdf"'),
        ({}, '{}'),
        ([], '[]'),
        (True, 'true'),
        (False, 'false'),
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
