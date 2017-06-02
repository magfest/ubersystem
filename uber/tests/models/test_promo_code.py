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


class TestPromoCodeSessionMixin:
    disambiguated_promo_code_id = 'b32a41bd-828f-4169-88fe-f7f3ad4138dc'

    @pytest.fixture
    def disambiguated_promo_code(self):
        with Session() as session:
            session.add(PromoCode(
                id=self.disambiguated_promo_code_id, code='012568'))

        with Session() as session:
            promo_code = session.query(PromoCode).filter(
                PromoCode.id == self.disambiguated_promo_code_id).one()
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
