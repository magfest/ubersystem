from datetime import datetime, timedelta

import pytest
import pytz
from mock import Mock

from uber.models import Attendee, Group, PromoCode, Session
from uber.config import c
from uber.payments import PreregCart
from uber.utils import check


next_week = datetime.now(pytz.UTC) + timedelta(days=7)
last_week = datetime.now(pytz.UTC) - timedelta(days=7)


class TestPromoCodeAdjustments:

    @pytest.mark.parametrize('uses_allowed', [None, '', 0])
    def test_empty_uses_set_to_none(self, uses_allowed):
        promo_code = PromoCode(uses_allowed=uses_allowed)
        promo_code._attribute_adjustments()
        assert promo_code.uses_allowed is None
        assert promo_code.is_unlimited

    @pytest.mark.parametrize('discount', [None, '', 0])
    @pytest.mark.parametrize('discount_type', [
        PromoCode._FIXED_DISCOUNT,
        PromoCode._FIXED_PRICE,
        PromoCode._PERCENT_DISCOUNT])
    def test_empty_discount_set_to_none(self, discount, discount_type):
        promo_code = PromoCode(discount=discount, discount_type=discount_type)
        promo_code._attribute_adjustments()
        assert promo_code.discount is None
        assert promo_code.is_free

    @pytest.mark.parametrize('discount', [100, 200])
    def test_100_percent_discount_is_free(self, discount):
        promo_code = PromoCode(
            discount=discount,
            discount_type=PromoCode._PERCENT_DISCOUNT)
        promo_code._attribute_adjustments()
        assert promo_code.is_free

    @pytest.mark.parametrize('discount', [c.BADGE_PRICE, 20000])
    def test_badge_price_fixed_discount_is_free(self, discount):
        promo_code = PromoCode(
            discount=discount,
            discount_type=PromoCode._FIXED_DISCOUNT)
        promo_code._attribute_adjustments()
        assert promo_code.is_free

    @pytest.mark.parametrize('code', [None, '', '   ', 0])
    def test_empty_code_auto_generated(self, code, monkeypatch):
        monkeypatch.setattr(PromoCode, 'generate_random_code', Mock())
        promo_code = PromoCode(code=code)
        promo_code._attribute_adjustments()
        assert PromoCode.generate_random_code.called

    @pytest.mark.parametrize('code,expected', [
        ('asdf', 'asdf'),
        ('  asdf  ', 'asdf'),
        ('a  s  d  f', 'a s d f'),
        ('  a   sd   f  ', 'a sd f')])
    def test_code_whitespace_removal(self, code, expected):
        promo_code = PromoCode(code=code)
        promo_code._attribute_adjustments()
        assert expected == promo_code.code


class TestPromoCodeUse:

    @pytest.mark.parametrize('code,badge_cost,attr,value', [
        ('ten dollars off', 30, 'overridden_price', 30),
        ('ten percent off', 36, 'overridden_price', 36),
        ('ten dollar badge', 10, 'overridden_price', 10),
        ('free badge', 0, 'paid', c.NEED_NOT_PAY)])
    def test_discount(self, code, badge_cost, attr, value):
        attendee = Attendee()
        assert attendee.badge_cost == 40
        with Session() as session:
            attendee.promo_code = session.promo_code(code=code)
            assert attendee.badge_cost == badge_cost
            attendee._use_promo_code()
            assert getattr(attendee, attr) == value
            attendee.promo_code = None


class TestPromoCodeModelChecks:

    @pytest.mark.parametrize('discount,message', [
        ('a lot', "What you entered for the discount isn't even a number."),
        (-10, 'You cannot give out promo codes that increase badge prices.'),
        (None, None),
        ('', None),
        (0, None),
        (10, None)])
    def test_valid_discount(self, discount, message):
        assert message == check(PromoCode(discount=discount, uses_allowed=1))

    @pytest.mark.parametrize('uses_allowed,message', [
        ('a lot', "What you entered for the number of uses allowed isn't even a number."),
        (-10, 'Promo codes must have at least 0 uses remaining.'),
        (None, None),
        ('', None),
        (0, None),
        (10, None)])
    def test_valid_uses_allowed(self, uses_allowed, message):
        assert message == check(PromoCode(discount=1, uses_allowed=uses_allowed))

    @pytest.mark.parametrize('uses_allowed', [None, 0, ''])
    @pytest.mark.parametrize('discount', [None, 0, ''])
    def test_no_unlimited_free_badges(self, discount, uses_allowed):
        assert check(PromoCode(
            discount=discount,
            uses_allowed=uses_allowed)) == 'Unlimited-use, free-badge promo codes are not allowed.'

    @pytest.mark.parametrize('discount', [100, 101, 200])
    @pytest.mark.parametrize('uses_allowed', [None, 0, ''])
    def test_no_unlimited_100_percent_discount(self, discount, uses_allowed):
        assert check(PromoCode(
            discount=discount,
            discount_type=PromoCode._PERCENT_DISCOUNT,
            uses_allowed=uses_allowed)) == 'Unlimited-use, free-badge promo codes are not allowed.'

    @pytest.mark.parametrize('uses_allowed', [None, 0, ''])
    @pytest.mark.parametrize('discount', [c.BADGE_PRICE, c.BADGE_PRICE + 1])
    def test_no_unlimited_full_badge_discount(self, discount, uses_allowed):
        assert check(PromoCode(
            discount=discount,
            discount_type=PromoCode._FIXED_DISCOUNT,
            uses_allowed=uses_allowed)) == 'Unlimited-use, free-badge promo codes are not allowed.'

    @pytest.mark.parametrize('code', [
        'ten percent off',
        'ten dollars off',
        'ten dollar badge',
        'free badge',
        '  TEN   PERCENT     OFF ',
        '  TEN   DOLLARS     OFF ',
        '  TEN   DOLLAR     BADGE ',
        '  FREE   BADGE    '])
    def test_no_dupe_code(self, code):
        assert check(PromoCode(discount=1, code=code)) == \
            'The code you entered already belongs to another promo code. Note that promo codes are not case sensitive.'


class TestAttendeePromoCodeModelChecks:

    @pytest.mark.parametrize('paid', [c.PAID_BY_GROUP, c.NEED_NOT_PAY])
    def test_promo_code_is_useful_not_is_unpaid(self, paid):
        promo_code = PromoCode(discount=1, expiration_date=next_week)
        attendee = Attendee(
            paid=paid,
            promo_code=promo_code,
            placeholder=True,
            first_name='First',
            last_name='Last')
        assert check(attendee, prereg=True) == "You can't apply a promo code after you've paid or if you're in a group."

    def test_promo_code_is_useful_overridden_price(self):
        promo_code = PromoCode(discount=1, expiration_date=next_week)
        attendee = Attendee(
            overridden_price=10,
            promo_code=promo_code,
            placeholder=True,
            first_name='First',
            last_name='Last')
        assert check(attendee, prereg=True) == \
            "You already have a special badge price, you can't use a promo code on top of that."

    def test_promo_code_is_useful_special_price(self, monkeypatch):
        monkeypatch.setattr(c, 'get_attendee_price', lambda r: 0)
        promo_code = PromoCode(discount=1, expiration_date=next_week)
        attendee = Attendee(
            promo_code=promo_code,
            placeholder=True,
            first_name='First',
            last_name='Last')
        assert check(attendee, prereg=True) == \
            "That promo code doesn't make your badge any cheaper. You may already have other discounts."

    def test_promo_code_does_not_help_one_day_badge(self, monkeypatch):
        monkeypatch.setattr(c, 'get_oneday_price', lambda r: 10)
        promo_code = PromoCode(discount=1, expiration_date=next_week)
        attendee = Attendee(
            badge_type=c.ONE_DAY_BADGE,
            promo_code=promo_code,
            placeholder=True,
            first_name='First',
            last_name='Last')
        assert check(attendee, prereg=True) == \
            "You can't apply a promo code to a one day badge."

    def test_promo_code_does_not_help_dealer(self, monkeypatch):
        promo_code = PromoCode(discount=1, expiration_date=next_week)
        attendee = Attendee(
            badge_type=c.PSEUDO_DEALER_BADGE,
            group=Group(),
            cellphone='555-555-1234',
            promo_code=promo_code,
            placeholder=True,
            first_name='First',
            last_name='Last')
        assert check(attendee, prereg=True) == \
            "You can't apply a promo code to a dealer registration."

    def test_promo_code_does_not_help_minor(self, monkeypatch):
        promo_code = PromoCode(discount=1, expiration_date=next_week)
        attendee = Attendee(
            birthdate=last_week,
            promo_code=promo_code,
            placeholder=True,
            first_name='First',
            last_name='Last')
        assert check(attendee, prereg=True) == \
            "You are already receiving an age based discount, you can't use a promo code on top of that."

    def test_promo_code_not_is_expired(self):
        expire = datetime.now(pytz.UTC) - timedelta(days=9)
        promo_code = PromoCode(discount=1, expiration_date=expire)
        attendee = Attendee(
            promo_code=promo_code,
            placeholder=True,
            first_name='First',
            last_name='Last')
        assert check(attendee, prereg=True) == 'That promo code is expired.'

    def test_promo_code_has_uses_remaining(self):
        promo_code = PromoCode(uses_allowed=1, expiration_date=next_week)
        sess = Attendee(
            promo_code=promo_code,
            placeholder=True,
            first_name='First',
            last_name='Last')
        PreregCart.unpaid_preregs[sess.id] = PreregCart.to_sessionized(sess)
        sess.promo_code = None
        sess.promo_code_id = None
        assert len(promo_code.valid_used_by) == 0

        attendee = Attendee(
            promo_code=promo_code,
            placeholder=True,
            first_name='First',
            last_name='Last')

        assert check(attendee, prereg=True) == 'That promo code has been used too many times.'


class TestPromoCodeSessionMixin:
    disambiguated_promo_code_id = 'b32a41bd-828f-4169-88fe-f7f3ad4138dc'

    @pytest.fixture
    def disambiguated_promo_code(self):
        with Session() as session:
            session.add(PromoCode(id=self.disambiguated_promo_code_id, code='012568', uses_allowed=100))

        with Session() as session:
            promo_code = session.query(PromoCode).filter(PromoCode.id == self.disambiguated_promo_code_id).one()
            yield promo_code
            session.delete(promo_code)

    def test_lookup_promo_code(self, disambiguated_promo_code):
        promo_code_id = disambiguated_promo_code.id
        with Session() as session:
            for s1 in '0OQD':
                for s2 in '1IL':
                    for s3 in '2Z':
                        for s4 in '5S':
                            for s5 in '6G':
                                for s6 in '8B':
                                    letters = [s1, s2, s3, s4, s5, s6]

                                    for s in ['', '-', ' ', '  ', '  --  -  ']:
                                        code = s.join(letters)
                                        p = session.lookup_promo_code(code)
                                        assert p.id == promo_code_id

                                        code = code.lower()
                                        p = session.lookup_promo_code(code)
                                        assert p.id == promo_code_id

    def test_lookup_promo_code_nonexistent(self):
        with Session() as session:
            assert session.lookup_promo_code(None) is None
            assert session.lookup_promo_code('') is None
            assert session.lookup_promo_code('NONEXISTENT') is None

    def test_attendee_promo_code_attr(self, disambiguated_promo_code):
        """
        Test that setting promo_code & promo_code_id have no affect on each
        other. We're testing this because the Attendee.promo_code relationship
        does not use the "save-update" cascade relationship, so these two
        properties should not update each other.
        """
        attendee = Attendee()

        attendee.promo_code = disambiguated_promo_code
        assert attendee.promo_code is not None
        assert attendee.promo_code_id is None

        attendee.promo_code_id = disambiguated_promo_code.id
        assert attendee.promo_code is not None
        assert attendee.promo_code_id is not None

        attendee.promo_code = None
        assert attendee.promo_code is None
        assert attendee.promo_code_id is not None

        attendee.promo_code_id = disambiguated_promo_code.id
        assert attendee.promo_code is None
        assert attendee.promo_code_id is not None

        attendee.promo_code_id = None
        assert attendee.promo_code is None
        assert attendee.promo_code_id is None

    @pytest.mark.parametrize('code,message,promo_code_id,promo_code_code', [
        (None, '', None, ''),
        ('', '', None, ''),
        ('012568', '', disambiguated_promo_code_id, '012568'),
        ('olzsgb', '', disambiguated_promo_code_id, '012568'),
        ('NONEXISTENT', 'The promo code you entered is invalid.', None, '')
    ])
    def test_add_promo_code_to_attendee(
            self,
            code,
            message,
            promo_code_id,
            promo_code_code,
            disambiguated_promo_code):

        with Session() as session:
            a = Attendee()
            assert message == session.add_promo_code_to_attendee(a, code)
            assert a.promo_code_id == promo_code_id
            assert a.promo_code_code == promo_code_code
