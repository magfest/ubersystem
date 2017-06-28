import re
from datetime import datetime

import cherrypy
import pytest
from uber.common import *
from uber.site_sections import budget
from uber.tests.conftest import admin_attendee, extract_message_from_html, \
    GET, POST
from uber.utils import CSRFException


class TestGeneratePromoCodes(object):

    def _generate_promo_codes_response(self, **params):
        response = budget.Root().generate_promo_codes(**params)
        if isinstance(response, bytes):
            response = response.decode('utf-8')
        response = response.strip()
        assert response.startswith('<!DOCTYPE HTML>')
        return response

    def test_GET(self, GET, admin_attendee):
        response = self._generate_promo_codes_response()
        message = extract_message_from_html(response)
        assert message == ''

    def test_POST_expiration_date(self, POST, csrf_token, admin_attendee):
        response = self._generate_promo_codes_response(
            is_single_promo_code=1,
            count=1,
            use_words=False,
            expiration_date='2111-01-01',
            code='Expires 2111',
            uses_allowed=1)

        expiration_date = c.EVENT_TIMEZONE.localize(datetime(2111, 1, 1))

        with Session() as session:
            promo_code = session.lookup_promo_code('Expires 2111')
            assert promo_code.expiration_date == expiration_date
