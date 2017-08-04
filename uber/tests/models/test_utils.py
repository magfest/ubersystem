from uber.tests import *
from uber.utils import add_opt, remove_opt


@pytest.fixture
def base_url(monkeypatch):
    monkeypatch.setattr(c, 'URL_BASE', 'https://server.com/uber')


def test_absolute_urls(base_url):
    assert convert_to_absolute_url('../somepage.html') == 'https://server.com/uber/somepage.html'


def test_absolute_urls_empty(base_url):
    assert convert_to_absolute_url(None) == ''
    assert convert_to_absolute_url('') == ''


def test_absolute_url_error(base_url):
    with pytest.raises(ValueError) as e_info:
        convert_to_absolute_url('..')

    with pytest.raises(ValueError) as e_info:
        convert_to_absolute_url('.')

    with pytest.raises(ValueError) as e_info:
        convert_to_absolute_url('////')


class TestAddRemoveOpts:
    def test_add_opt_empty(self):
        assert str(c.DEALER_RIBBON) == add_opt(Attendee().ribbon_ints, c.DEALER_RIBBON)

    def test_add_opt_duplicate(self):
        assert str(c.DEALER_RIBBON) == add_opt(Attendee(ribbon=c.DEALER_RIBBON).ribbon_ints, c.DEALER_RIBBON)

    def test_add_opt_second(self):
        # add_opt doesn't preserve order and isn't meant to, so convert both values to sets
        # otherwise this unit test fails randomly
        assert set([str(c.VOLUNTEER_RIBBON), str(c.DEALER_RIBBON)]) == \
               set(add_opt(Attendee(ribbon=c.VOLUNTEER_RIBBON).ribbon_ints, c.DEALER_RIBBON).split(','))

    def test_remove_opt_empty(self):
        assert '' == remove_opt(Attendee().ribbon_ints, c.DEALER_RIBBON)

    def test_remove_opt_only(self):
        assert '' == remove_opt(Attendee(ribbon=c.DEALER_RIBBON).ribbon_ints, c.DEALER_RIBBON)

    def test_remove_opt_second(self):
        assert str(c.DEALER_RIBBON) == \
               remove_opt(Attendee(ribbon=','.join([str(c.VOLUNTEER_RIBBON), str(c.DEALER_RIBBON)])).ribbon_ints, c.VOLUNTEER_RIBBON)


class TestCharge:
    def test_charge_one_email(self):
        attendee = Attendee(email='test@example.com')
        charge = Charge(targets=[attendee])
        assert charge.receipt_email == attendee.email

    def test_charge_group_leader_email(self):
        attendee = Attendee(email='test@example.com')
        group = Group(attendees=[attendee])
        charge = Charge(targets=[group])
        assert charge.receipt_email == attendee.email

    def test_charge_first_email(self):
        attendee = Attendee(email='test@example.com')
        charge = Charge(targets=[attendee, Attendee(email='test2@example.com'), Attendee(email='test3@example.com')])
        assert charge.receipt_email == attendee.email

    def test_charge_no_email(self):
        charge = Charge(targets=[Group()])
        assert charge.receipt_email is None

    def test_charge_log_transaction(self):
        attendee = Attendee()
        charge = Charge(targets=[attendee],
                        amount=1000,
                        description="Test charge")
        charge.response = stripe.Charge(id=10)
        result = charge.stripe_transaction_from_charge()
        assert result.stripe_id == 10
        assert result.amount == 1000
        assert result.desc == "Test charge"
        assert result.type == c.PAYMENT
        assert result.who == 'non-admin'
        assert result.fk_id == attendee.id
        assert result.fk_model == attendee.__class__.__name__

    def test_charge_log_transaction_no_model(self):
        stripe.Charge.create = Mock(return_value=1)
        Charge.stripe_transaction_from_charge = Mock()
        charge = Charge(amount=1000, description="Test charge")
        Charge.charge_cc(charge, Mock(), 1)
        assert not Charge.stripe_transaction_from_charge.called
