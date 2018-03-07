"""
Tests for uber.automated_emails.AutomatedEmailFixture.
"""

import pytest
from jinja2.exceptions import TemplateNotFound

from uber.automated_emails import AutomatedEmailFixture
from uber.models import Attendee

from tests.uber.email_tests.email_fixtures import *  # noqa: F401,F403


class TestAutomatedEmailFixture(object):

    @pytest.mark.parametrize('ident', [
        pytest.param(None, marks=pytest.mark.xfail(raises=AssertionError)),
        pytest.param('', marks=pytest.mark.xfail(raises=AssertionError)),
    ])
    def test_empty_ident(self, clear_automated_email_fixtures, render_empty_attendee_template, ident):
        AutomatedEmailFixture(Attendee, 'subject', 'template.txt', lambda x: True, ident)

    def test_duplicate_ident(self, clear_automated_email_fixtures, render_empty_attendee_template):
        AutomatedEmailFixture(Attendee, 'subject', 'template.txt', lambda x: True, 'ident')
        with pytest.raises(AssertionError):
            AutomatedEmailFixture(Attendee, 'subject', 'template.txt', lambda x: True, 'ident')

    def test_invalid_template(self, clear_automated_email_fixtures):
        with pytest.raises(TemplateNotFound):
            AutomatedEmailFixture(Attendee, 'subject', 'template.txt', lambda x: True, 'ident')
