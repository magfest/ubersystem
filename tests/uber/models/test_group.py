from datetime import datetime

import pytest
from mock import Mock
from pytz import UTC

from uber.config import c
from uber.models import Attendee, Group, Session
from uber.utils import localized_now


@pytest.fixture
def session(request, monkeypatch):
    session = Session()
    request.addfinalizer(session.close)
    monkeypatch.setattr(session, 'add', Mock())
    monkeypatch.setattr(session, 'delete', Mock())
    return session


def test_cost_presave_adjustment():
    g = Group(cost=123, auto_recalc=False)
    g.presave_adjustments()
    assert g.cost == 123

    g.auto_recalc = True
    g.presave_adjustments()
    assert g.cost == 0

    g.auto_recalc = False
    g.cost = ''
    g.presave_adjustments()
    assert g.cost == 0

    g.auto_recalc = False
    g.cost = 10
    g.presave_adjustments()
    assert g.cost == 10

    g.amount_paid = ''
    g.presave_adjustments()
    assert g.amount_paid == 0

    g.amount_refunded = ''
    g.presave_adjustments()
    assert g.amount_refunded == 0


def test_approved_presave_adjustment():
    g = Group()
    g.presave_adjustments()
    assert g.approved is None

    g.status = c.APPROVED
    g.presave_adjustments()
    assert g.approved is not None


def test_is_dealer():
    assert not Group().is_dealer
    assert Group(tables=1).is_dealer
    assert not Group(tables=1, registered=datetime.now(UTC)).is_dealer
    assert Group(tables=1, registered=datetime.now(UTC), amount_paid=1).is_dealer
    assert Group(tables=1, registered=datetime.now(UTC), cost=1).is_dealer


def test_is_unpaid():
    assert not Group().is_unpaid
    assert not Group(amount_paid=1).is_unpaid
    assert not Group(amount_paid=1, cost=1).is_unpaid
    assert Group(cost=1).is_unpaid


def test_table_cost():
    assert 0 == Group().table_cost
    assert 100 == Group(tables=1).table_cost
    assert 300 == Group(tables=2).table_cost
    assert 600 == Group(tables=3).table_cost
    assert 1000 == Group(tables=4).table_cost
    assert 1400 == Group(tables=5).table_cost
    assert 1800 == Group(tables=6).table_cost


def test_amount_unpaid(monkeypatch):
    assert 0 == Group(registered=datetime.now(UTC)).amount_unpaid
    assert 222 == Group(registered=datetime.now(UTC), cost=222).amount_unpaid
    assert 111 == Group(registered=datetime.now(UTC), cost=222, amount_paid=111).amount_unpaid
    assert 0 == Group(registered=datetime.now(UTC), cost=222, amount_paid=222).amount_unpaid
    monkeypatch.setattr(Group, 'default_cost', 333)
    assert 333 == Group().amount_unpaid


def test_min_badges_addable():
    assert 5 == Group().min_badges_addable
    assert 1 == Group(can_add=True).min_badges_addable


def test_new_ribbon():
    assert '' == Group().new_ribbon
    assert '' == Group(attendees=[Attendee()]).new_ribbon
    assert c.DEALER_RIBBON == Group(tables=1).new_ribbon


def test_email():
    assert not Group().email
    assert not Group(attendees=[Attendee()]).email
    assert 'a@b.c' == Group(attendees=[Attendee(email='a@b.c')]).email
    assert not Group(attendees=[Attendee(email='a@b.c'), Attendee(email='d@e.f')]).email

    assert not Group(leader=Attendee()).email
    assert 'a@b.c' == Group(leader=Attendee(email='a@b.c')).email
    assert 'a@b.c' == Group(leader=Attendee(email='a@b.c'), attendees=[Attendee(email='d@e.f')]).email
    assert 'a@b.c' == Group(
        leader=Attendee(email='a@b.c'), attendees=[Attendee(email='d@e.f'), Attendee(email='g@h.i')]).email

    assert 'd@e.f' == Group(leader=Attendee(), attendees=[Attendee(email='d@e.f')]).email
    assert not Group(leader=Attendee(), attendees=[Attendee(email='d@e.f'), Attendee(email='g@h.i')]).email


def test_badges():
    assert 0 == Group().badges
    assert 1 == Group(attendees=[Attendee()]).badges
    assert 2 == Group(attendees=[Attendee(), Attendee()]).badges


def test_unregistered_badges():
    assert 0 == Group().unregistered_badges
    assert 0 == Group(attendees=[Attendee(first_name='x')]).unregistered_badges
    assert 1 == Group(attendees=[Attendee()]).unregistered_badges
    assert 2 == Group(attendees=[Attendee(), Attendee(first_name='x'), Attendee()]).unregistered_badges


def test_badges_purchased():
    assert 0 == Group().badges_purchased
    assert 0 == Group(attendees=[Attendee()]).badges_purchased
    assert 1 == Group(attendees=[Attendee(paid=c.PAID_BY_GROUP)]).badges_purchased
    assert 2 == Group(attendees=[
        Attendee(paid=c.PAID_BY_GROUP), Attendee(paid=c.PAID_BY_GROUP),
        Attendee(paid=c.NOT_PAID), Attendee(paid=c.HAS_PAID), Attendee(paid=c.REFUNDED), Attendee(paid=c.NEED_NOT_PAY)
    ]).badges_purchased


def test_assign_new_badges(session, monkeypatch):
    monkeypatch.setattr(Group, 'new_ribbon', 111)
    group = Group()
    session.assign_badges(group, '2', 222)
    assert 2 == group.badges == len(group.attendees)
    for attendee in group.attendees:
        assert attendee.paid == c.PAID_BY_GROUP
        assert attendee.ribbon == 111
        assert attendee.badge_type == 222


def test_assign_new_comped_badges(session, monkeypatch):
    group = Group()
    session.assign_badges(group, 2, paid=c.NEED_NOT_PAY)
    assert 2 == group.badges == len(group.attendees)
    for attendee in group.attendees:
        assert attendee.paid == c.NEED_NOT_PAY


def test_assign_extra_create_arguments(session):
    group = Group()
    registered = localized_now()
    session.assign_badges(group, 2, registered=registered)
    assert 2 == group.badges == len(group.attendees)
    for attendee in group.attendees:
        assert attendee.registered == registered


def test_assign_removing_too_many_badges(session):
    assert not session.assign_badges(Group(attendees=[Attendee(paid=c.PAID_BY_GROUP)]), 0)
    assert 'You cannot' in session.assign_badges(Group(attendees=[Attendee(paid=c.HAS_PAID)]), 0)
    assert 'You cannot' in session.assign_badges(Group(attendees=[Attendee(first_name='x')]), 0)


def test_assign_removing_badges(monkeypatch, session):
    monkeypatch.setattr(Attendee, 'registered', datetime.now(UTC))
    attendees = [
        Attendee(paid=c.PAID_BY_GROUP),
        Attendee(first_name='x'),
        Attendee(paid=c.HAS_PAID),
        Attendee(paid=c.PAID_BY_GROUP)]
    group = Group(attendees=attendees)
    session.assign_badges(group, 2)
    assert group.badges == 2
    assert session.delete.call_count == 2
    session.delete.assert_any_call(attendees[0])
    session.delete.assert_any_call(attendees[3])


def test_assign_custom_badges_after_deadline(session, after_printed_badge_deadline):
    group = Group()
    message = session.assign_badges(group, 2, new_badge_type=c.STAFF_BADGE)
    assert message and 'ordered' in message


def test_badge_cost(monkeypatch, clear_price_bumps):
    monkeypatch.setattr(c, 'get_group_price', Mock(return_value=c.DEALER_BADGE_PRICE + 10))
    assert 4 * c.DEALER_BADGE_PRICE + 20 == Group(attendees=[
        Attendee(paid=c.REFUNDED), Attendee(ribbon=c.DEALER_RIBBON),
        Attendee(paid=c.PAID_BY_GROUP), Attendee(paid=c.PAID_BY_GROUP),
        Attendee(paid=c.PAID_BY_GROUP, ribbon=c.DEALER_RIBBON), Attendee(paid=c.PAID_BY_GROUP, ribbon=c.DEALER_RIBBON)
    ]).badge_cost


def test_new_extra():
    assert 0 == Group().amount_extra
    assert 20 == Group(attendees=[Attendee(paid=c.PAID_BY_GROUP, amount_extra=20)]).amount_extra
    assert 30 == Group(attendees=[
        Attendee(paid=c.PAID_BY_GROUP, amount_extra=10),
        Attendee(paid=c.PAID_BY_GROUP, amount_extra=20)
    ]).amount_extra


def test_existing_extra(monkeypatch):
    monkeypatch.setattr(Group, 'is_new', False)
    assert 0 == Group(attendees=[Attendee(paid=c.PAID_BY_GROUP, amount_extra=20)]).amount_extra


def test_group_badge_status_cascade():
    g = Group(cost=0, auto_recalc=False)
    taken = Attendee(
        group_id=g.id, paid=c.PAID_BY_GROUP, badge_status=c.NEW_STATUS, first_name='Liam', last_name='Neeson')
    floating = Attendee(group_id=g.id, paid=c.PAID_BY_GROUP, badge_status=c.NEW_STATUS)
    g.attendees = [taken, floating]
    g.presave_adjustments()
    assert taken.badge_status == c.COMPLETED_STATUS and floating.badge_status == c.NEW_STATUS
