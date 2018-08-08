from datetime import datetime

from tests.uber.conftest import admin_attendee, extract_message_from_html, GET, POST
from uber.config import c
from uber.models import Session
from uber.site_sections import budget


assert admin_attendee
assert GET
assert POST


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
        self._generate_promo_codes_response(
            is_single_promo_code=1,
            count=1,
            use_words=False,
            expiration_date='2111-01-01',
            code='Expires 2111',
            uses_allowed=1)

        expiration_date = c.EVENT_TIMEZONE.localize(datetime(2111, 1, 1, 23, 59, 59))

        with Session() as session:
            promo_code = session.lookup_promo_code('Expires 2111')
            assert promo_code.expiration_date == expiration_date
