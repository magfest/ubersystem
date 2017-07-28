from uber.tests import *


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
