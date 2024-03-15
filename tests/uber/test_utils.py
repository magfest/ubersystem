from datetime import date, timedelta

import jinja2
import pytest
import stripe
from mock import Mock

from uber.config import c
from uber.models import Attendee, Group
from uber.utils import add_opt, convert_to_absolute_url, get_age_from_birthday, localized_now, \
    remove_opt, normalize_newlines
from uber.payments import PreregCart


@pytest.fixture
def base_url(monkeypatch):
    monkeypatch.setattr(c, 'PATH', '/uber')
    monkeypatch.setattr(c, 'URL_ROOT', 'https://server.com')
    monkeypatch.setattr(c, 'URL_BASE', 'https://server.com/uber')


def test_absolute_urls(base_url):
    assert convert_to_absolute_url('../somepage.html') == 'https://server.com/uber/somepage.html'


def test_absolute_urls_relative_root(base_url):
    assert convert_to_absolute_url('/uber/somepage.html') == 'https://server.com/uber/somepage.html'


def test_absolute_urls_already_absolute(base_url):
    assert convert_to_absolute_url('https://server.com/uber/somepage.html') == 'https://server.com/uber/somepage.html'


def test_absolute_urls_empty(base_url):
    assert convert_to_absolute_url(None) == ''
    assert convert_to_absolute_url('') == ''


def test_absolute_url_error(base_url):
    with pytest.raises(ValueError):
        convert_to_absolute_url('..')

    with pytest.raises(ValueError):
        convert_to_absolute_url('.')

    with pytest.raises(ValueError):
        convert_to_absolute_url('////')

    with pytest.raises(ValueError):
        convert_to_absolute_url('https://server.com/somepage.html')


@pytest.mark.parametrize('test_input,expected', [
    (None, ''),
    ('', ''),
    ([], ''),
    ({}, ''),
    (jinja2.runtime.Undefined(), ''),
    ('\n', '\n'),
    ('\r', '\n'),
    ('\r\n', '\n'),
    ('asdf\nzxcv', 'asdf\nzxcv'),
    ('asdf\rzxcv', 'asdf\nzxcv'),
    ('asdf\r\nzxcv', 'asdf\nzxcv')
])
def test_normalize_newlines(test_input, expected):
    assert expected == normalize_newlines(test_input)


class TestAddRemoveOpts:
    def test_add_opt_empty(self):
        assert str(c.DEALER_RIBBON) == add_opt(Attendee().ribbon_ints, c.DEALER_RIBBON)

    def test_add_opt_duplicate(self):
        assert str(c.DEALER_RIBBON) == add_opt(Attendee(ribbon=c.DEALER_RIBBON).ribbon_ints, c.DEALER_RIBBON)

    def test_add_opt_second(self):
        # add_opt doesn't preserve order and isn't meant to, so convert both values to sets
        # otherwise this unit test fails randomly
        assert set([str(c.VOLUNTEER_RIBBON), str(c.DEALER_RIBBON)]) == set(
            add_opt(Attendee(ribbon=c.VOLUNTEER_RIBBON).ribbon_ints, c.DEALER_RIBBON).split(','))

    def test_remove_opt_empty(self):
        assert '' == remove_opt(Attendee().ribbon_ints, c.DEALER_RIBBON)

    def test_remove_opt_only(self):
        assert '' == remove_opt(Attendee(ribbon=c.DEALER_RIBBON).ribbon_ints, c.DEALER_RIBBON)

    def test_remove_opt_second(self):
        assert str(c.DEALER_RIBBON) == remove_opt(
            Attendee(ribbon=','.join([str(c.VOLUNTEER_RIBBON), str(c.DEALER_RIBBON)])).ribbon_ints, c.VOLUNTEER_RIBBON)


<<<<<<< HEAD
=======
class TestPreregCart:
    def test_charge_one_email(self):
        attendee = Attendee(email='test@example.com')
        charge = PreregCart(targets=[attendee])
        assert charge.receipt_email == attendee.email

    def test_charge_group_leader_email(self):
        attendee = Attendee(email='test@example.com')
        group = Group(attendees=[attendee])
        charge = PreregCart(targets=[group])
        assert charge.receipt_email == attendee.email

    def test_charge_first_email(self):
        attendee = Attendee(email='test@example.com')
        charge = PreregCart(targets=[attendee, Attendee(email='test2@example.com'),
                                     Attendee(email='test3@example.com')])
        assert charge.receipt_email == attendee.email

    def test_charge_no_email(self):
        charge = PreregCart(targets=[Group()])
        assert charge.receipt_email is None

    def test_charge_log_transaction(self, monkeypatch):
        attendee = Attendee()
        monkeypatch.setattr(Attendee, 'amount_unpaid', 10)
        charge = PreregCart(targets=[attendee], amount=1000, description="Test charge")
        charge.response = stripe.Charge(id=10)
        result = charge.stripe_transaction_from_charge()
        assert result.stripe_id == 10
        assert result.amount == 1000
        assert result.desc == "Test charge"
        assert result.type == c.PAYMENT
        assert result.who == 'non-admin'

    def test_charge_log_transaction_attendee(self, monkeypatch):
        attendee = Attendee()
        monkeypatch.setattr(Attendee, 'amount_unpaid', 10)
        charge = PreregCart(targets=[attendee],
                            description="Test charge")
        charge.response = stripe.Charge(id=10)
        txn = charge.stripe_transaction_from_charge()
        result = charge.stripe_transaction_for_model(attendee, txn)
        assert result.attendee_id == attendee.id
        assert result.txn_id == txn.id
        assert result.share == 1000

    def test_charge_log_transaction_group(self, monkeypatch):
        group = Group()
        monkeypatch.setattr(Group, 'amount_unpaid', 10)
        charge = PreregCart(targets=[group],
                            description="Test charge")
        charge.response = stripe.Charge(id=10)
        txn = charge.stripe_transaction_from_charge()
        result = charge.stripe_transaction_for_model(group, txn)
        assert result.group_id == group.id
        assert result.txn_id == txn.id
        assert result.share == 1000

    def test_charge_log_transaction_no_unpaid(self, monkeypatch):
        group = Group()
        monkeypatch.setattr(Group, 'amount_unpaid', 0)
        charge = PreregCart(targets=[group], amount=1000,
                            description="Test charge")
        charge.response = stripe.Charge(id=10)
        txn = charge.stripe_transaction_from_charge()
        result = charge.stripe_transaction_for_model(group, txn)
        assert result.group_id == group.id
        assert result.txn_id == txn.id
        assert result.share == 1000

    def test_charge_log_transaction_no_model(self):
        stripe.Charge.create = Mock(return_value=1)
        PreregCart.stripe_transaction_from_charge = Mock()
        charge = PreregCart(amount=1000, description="Test charge")
        PreregCart.charge_cc(charge, Mock(), 1)
        assert not PreregCart.stripe_transaction_from_charge.called


>>>>>>> main
class TestAgeCalculations:

    @pytest.mark.parametrize('birthdate,today,expected', [
        # general
        (date(2000, 1, 1), date(2010, 1, 1), 10),
        (date(2000, 1, 1), date(2010, 6, 1), 10),
        (date(2000, 1, 1), date(2009, 6, 1), 9),
        (date(2000, 7, 31), date(2010, 7, 30), 9),
        (date(2000, 7, 31), date(2010, 7, 31), 10),
        (date(2000, 7, 31), date(2010, 8, 1), 10),
        (date(2000, 10, 4), date(2017, 10, 3), 16),
        (date(2000, 10, 4), date(2017, 10, 4), 17),
        # feb 29 birthday
        (date(2000, 2, 29), date(2010, 2, 28), 9),
        (date(2000, 2, 29), date(2010, 3, 1), 10),
        # feb 29 birthday + feb 29 today
        (date(2000, 2, 29), date(2008, 2, 28), 7),
        (date(2000, 2, 29), date(2008, 2, 29), 8),
        (date(2000, 2, 29), date(2008, 3, 1), 8),
        # feb 29 today
        (date(2000, 3, 1), date(2008, 2, 28), 7),
        (date(2000, 3, 1), date(2008, 2, 29), 7),
        (date(2000, 3, 1), date(2008, 3, 1), 8),
        # turning 18
        (date(2000, 1, 4), date(2018, 1, 3), 17),
        (date(2000, 1, 4), date(2018, 1, 4), 18),
        (date(2000, 1, 5), date(2018, 1, 4), 17),
        # turning 21
        (date(1997, 1, 4), date(2018, 1, 3), 20),
        (date(1997, 1, 4), date(2018, 1, 4), 21),
        (date(1997, 1, 5), date(2018, 1, 4), 20)

    ])
    def test_age_calculation(self, birthdate, today, expected):
        assert expected == get_age_from_birthday(birthdate, today)

    @pytest.mark.parametrize('birthdate_delta,expected', [
        (timedelta(days=200), 0),
        (timedelta(days=400), 1),
        (timedelta(days=800), 2),
        (timedelta(days=1200), 3),
        (timedelta(days=1500), 4),
    ])
    def test_default_today(self, birthdate_delta, expected):
        birthdate = localized_now() - birthdate_delta
        assert expected == get_age_from_birthday(birthdate)
