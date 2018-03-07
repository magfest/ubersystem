"""
Test fixtures used by all our email related tests.
"""

from collections import OrderedDict
from unittest.mock import Mock

import pytest
from pockets import listify

from uber import decorators
from uber.amazon_ses import AmazonSES
from uber.config import c
from uber.models import AutomatedEmail


@pytest.fixture(autouse=True)
def mock_send_email(monkeypatch):
    monkeypatch.setattr(c, 'DEV_BOX', False)
    monkeypatch.setattr(c, 'SEND_EMAILS', True)
    monkeypatch.setattr(AmazonSES, 'sendEmail', Mock(return_value=None))
    return AmazonSES.sendEmail


@pytest.fixture
def clear_automated_email_fixtures(monkeypatch):
    monkeypatch.setattr(AutomatedEmail, '_fixtures', OrderedDict())


@pytest.fixture
def render_empty_attendee_template(monkeypatch):
    def _render_empty(template_name_list):
        if listify(template_name_list)[0].endswith('.txt'):
            return '{{ attendee.full_name }}\n{{ c.EVENT_NAME }}\n{{ extra_data }}'
        return '<html><body>{{ attendee.full_name }}<br>{{ c.EVENT_NAME }}<br>{{ extra_data }}</body></html>'
    monkeypatch.setattr(decorators, 'render_empty', _render_empty)
