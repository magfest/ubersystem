from uber.tests import *


class TestPromoCodeAdjustments:
    def test_generate_code_no_stubs(self, monkeypatch):
        monkeypatch.setattr(c, 'PROMO_CODE_STUBS', {})
        regexp = '\w{' + str(c.PROMO_CODE_LENGTH) + '}'
        assert re.match(regexp, PromoCode().generate_code())

    def test_generate_code_with_stubs(self, monkeypatch):
        monkeypatch.setattr(c, 'PROMO_CODE_STUBS', {1: 'Alpha'})
        regexp = '\w{' + str(c.PROMO_CODE_LENGTH) + ',}'
        assert re.match(regexp, PromoCode().generate_code())

    def test_empty_uses_set_to_none(self):
        p = PromoCode(uses='')
        p._empty_adjustments()
        assert p.uses is None

    def test_empty_discount_set_to_none(self):
        p = PromoCode(discount='')
        p._empty_adjustments()
        assert p.discount is None

    def test_empty_code_auto_generated(self, monkeypatch):
        monkeypatch.setattr(PromoCode, 'generate_code', Mock())
        p = PromoCode(code='')
        p._generate_code()
        assert PromoCode.generate_code.called


class TestPromoCodeUse:
    def test_set_price_use(self):
        p = PromoCode(code='testcode', price='30')
        a = Attendee(code='testcode')
        a._use_promo_code
        assert a.overridden_price == 30

    def test_discount_use(self, monkeypatch):
        monkeypatch.setattr(c, 'get_attendee_price', Mock(return_value=20))
        p = PromoCode(code='testcode', discount='10')
        a = Attendee(code='testcode')
        a._use_promo_code
        assert a.overridden_price == 10

    def test_makes_badge_free_use(self):
        p = PromoCode(code='testcode', price='0')
        a = Attendee(code='testcode')
        a._use_promo_code
        assert a.paid == c.NEED_NOT_PAY

    def test_already_overridden(self):
        p = PromoCode(code='testcode', discount='10')
        a = Attendee(code='testcode', overridden_price=50)
        a._use_promo_code
        assert a.overridden_price == 50

    def test_already_paid(self):
        p = PromoCode(code='testcode', discount='10')
        a = Attendee(code='testcode', paid=c.HAS_PAID)
        a._use_promo_code
        assert not a.overridden_price

    def test_paid_by_group(self):
        p = PromoCode(code='testcode', discount='10')
        a = Attendee(code='testcode', paid=c.PAID_BY_GROUP)
        a._use_promo_code
        assert not a.overridden_price
