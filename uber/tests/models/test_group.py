from uber.tests import *

@pytest.fixture
def session(request, monkeypatch):
    session = Session().session
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

def test_approved_presave_adjustment():
    g = Group()
    g.presave_adjustments()
    assert g.approved is None

    g.status = APPROVED
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
    assert 125 == Group(tables=1).table_cost
    assert 300 == Group(tables=2).table_cost
    assert 525 == Group(tables=3).table_cost
    assert 825 == Group(tables=4).table_cost
    assert 1125 == Group(tables=5).table_cost

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

def test_new_badge_type():
    assert ATTENDEE_BADGE == Group().new_badge_type
    assert ATTENDEE_BADGE == Group(attendees=[Attendee()]).new_badge_type
    assert ATTENDEE_BADGE == Group(attendees=[Attendee(badge_type=SUPPORTER_BADGE)]).new_badge_type
    assert GUEST_BADGE == Group(attendees=[Attendee(badge_type=GUEST_BADGE)]).new_badge_type
    assert GUEST_BADGE == Group(attendees=[Attendee(), Attendee(badge_type=GUEST_BADGE)]).new_badge_type

def test_new_ribbon():
    assert NO_RIBBON == Group().new_ribbon
    assert NO_RIBBON == Group(attendees=[Attendee()]).new_ribbon
    assert DEALER_RIBBON == Group(tables=1).new_ribbon
    assert DEALER_RIBBON == Group(attendees=[Attendee(ribbon=DEALER_RIBBON)]).new_ribbon
    assert DEALER_RIBBON == Group(attendees=[Attendee(ribbon=DEALER_RIBBON), Attendee(ribbon=BAND_RIBBON)]).new_ribbon
    assert BAND_RIBBON == Group(attendees=[Attendee(ribbon=BAND_RIBBON)]).new_ribbon

def test_email():
    assert not Group().email
    assert not Group(attendees=[Attendee()]).email
    assert 'a@b.c' == Group(attendees=[Attendee(email='a@b.c')]).email
    assert not Group(attendees=[Attendee(email='a@b.c'), Attendee(email='d@e.f')]).email

    assert not Group(leader=Attendee()).email
    assert 'a@b.c' == Group(leader=Attendee(email='a@b.c')).email
    assert 'a@b.c' == Group(leader=Attendee(email='a@b.c'), attendees=[Attendee(email='d@e.f')]).email
    assert 'a@b.c' == Group(leader=Attendee(email='a@b.c'), attendees=[Attendee(email='d@e.f'), Attendee(email='g@h.i')]).email

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
    assert 1 == Group(attendees=[Attendee(paid=PAID_BY_GROUP)]).badges_purchased
    assert 2 == Group(attendees=[
        Attendee(paid=PAID_BY_GROUP), Attendee(paid=PAID_BY_GROUP),
        Attendee(paid=NOT_PAID), Attendee(paid=HAS_PAID), Attendee(paid=REFUNDED), Attendee(paid=NEED_NOT_PAY)
    ]).badges_purchased

def test_assign_new_badges(session, monkeypatch):
    monkeypatch.setattr(Group, 'new_ribbon', 111)
    monkeypatch.setattr(Group, 'new_badge_type', 222)
    group = Group()
    session.assign_badges(group, '2')
    assert 2 == group.badges == len(group.attendees)
    for attendee in group.attendees:
        assert attendee.paid == PAID_BY_GROUP
        assert attendee.ribbon == 111
        assert attendee.badge_type == 222

def test_assign_removing_too_many_badges(session):
    assert not session.assign_badges(Group(attendees=[Attendee(paid=PAID_BY_GROUP)]), 0)
    assert 'You cannot' in session.assign_badges(Group(attendees=[Attendee(paid=HAS_PAID)]), 0)
    assert 'You cannot' in session.assign_badges(Group(attendees=[Attendee(first_name='x')]), 0)

def test_assign_removing_badges(session):
    attendees = [Attendee(paid=PAID_BY_GROUP), Attendee(first_name='x'), Attendee(paid=HAS_PAID), Attendee(paid=PAID_BY_GROUP)]
    session.assign_badges(Group(attendees=attendees), 2)
    assert session.delete.call_count == 2
    session.delete.assert_any_call(attendees[0])
    session.delete.assert_any_call(attendees[3])

def test_badge_cost(monkeypatch):
    monkeypatch.setattr(state, 'get_group_price', Mock(return_value=DEALER_BADGE_PRICE + 10))
    assert 4 * DEALER_BADGE_PRICE + 20 == Group(attendees=[
        Attendee(paid=REFUNDED), Attendee(ribbon=DEALER_RIBBON),
        Attendee(paid=PAID_BY_GROUP), Attendee(paid=PAID_BY_GROUP),
        Attendee(paid=PAID_BY_GROUP, ribbon=DEALER_RIBBON), Attendee(paid=PAID_BY_GROUP, ribbon=DEALER_RIBBON)
    ]).badge_cost
