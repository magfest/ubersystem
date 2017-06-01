from uber.tests import *


class TestPromoCodeAdjustments:

    @pytest.mark.parametrize('uses_allowed', [None, '', 0])
    def test_empty_uses_set_to_none(self, uses_allowed):
        promo_code = PromoCode(uses_allowed=uses_allowed)
        promo_code._attribute_adjustments()
        assert promo_code.uses_allowed is None

    @pytest.mark.parametrize('discount', [None, '', 0])
    def test_empty_discount_set_to_none(self, discount):
        promo_code = PromoCode(discount=discount)
        promo_code._attribute_adjustments()
        assert promo_code.discount is None

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
