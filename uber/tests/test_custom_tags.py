import pytest

from uber.common import *
from uber.custom_tags import linebreaksbr


class TestLinebreaksbr(object):

    @pytest.mark.parametrize("test_input,expected", [
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
