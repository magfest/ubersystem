"""
Factory-boy factories for creating test data.

Usage in tests:
    from tests.uber.factories import AttendeeFactory, DepartmentFactory

    def test_something():
        attendee = AttendeeFactory(first_name='Alice', badge_type=c.STAFF_BADGE)
        department = DepartmentFactory(name='Arcade')
"""
from datetime import date, timedelta

import factory

from uber.config import c
from uber.models import (
    Attendee, Department, DeptMembership, DeptRole,
    Group, Job, PromoCode, Session, WatchList,
)


class UberModelFactory(factory.Factory):
    """Base factory that uses the uber Session to persist objects."""

    class Meta:
        abstract = True

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        with Session() as session:
            obj = model_class(*args, **kwargs)
            session.add(obj)
            session.commit()
            session.refresh(obj)
            session.expunge(obj)
            return obj


class AttendeeFactory(UberModelFactory):
    class Meta:
        model = Attendee

    placeholder = True
    first_name = factory.Faker('first_name')
    last_name = factory.Faker('last_name')
    email = factory.Faker('email')
    badge_type = c.ATTENDEE_BADGE
    paid = c.NOT_PAID


class StaffAttendeeFactory(AttendeeFactory):
    badge_type = c.STAFF_BADGE
    paid = c.NEED_NOT_PAY
    staffing = True
    ribbon = c.VOLUNTEER_RIBBON


class DepartmentFactory(UberModelFactory):
    class Meta:
        model = Department

    name = factory.Sequence(lambda n: f'Test Department {n}')
    description = factory.LazyAttribute(lambda o: f'Description for {o.name}')


class DeptRoleFactory(UberModelFactory):
    class Meta:
        model = DeptRole

    name = factory.Sequence(lambda n: f'Role {n}')
    description = factory.LazyAttribute(lambda o: f'Description for {o.name}')
    department_id = None  # Must be supplied or use department subfactory


class DeptMembershipFactory(UberModelFactory):
    class Meta:
        model = DeptMembership

    attendee_id = None   # Must be supplied
    department_id = None  # Must be supplied
    is_dept_head = False


class JobFactory(UberModelFactory):
    class Meta:
        model = Job

    name = factory.Sequence(lambda n: f'Test Job {n}')
    start_time = factory.LazyAttribute(lambda o: c.EPOCH)
    duration = 2
    weight = 1
    slots = 1
    department_id = None  # Must be supplied


class GroupFactory(UberModelFactory):
    class Meta:
        model = Group

    name = factory.Faker('company')


class PromoCodeFactory(UberModelFactory):
    class Meta:
        model = PromoCode

    code = factory.Sequence(lambda n: f'TESTCODE{n}')
    discount = 10
    discount_type = PromoCode._FIXED_DISCOUNT


class PercentPromoCodeFactory(PromoCodeFactory):
    discount_type = PromoCode._PERCENT_DISCOUNT


class FixedPricePromoCodeFactory(PromoCodeFactory):
    discount_type = PromoCode._FIXED_PRICE


class FreePromoCodeFactory(PromoCodeFactory):
    discount = 0
    uses_allowed = 100


class WatchListFactory(UberModelFactory):
    class Meta:
        model = WatchList

    first_names = 'Banned, Alias'
    last_name = factory.Faker('last_name')
    email = factory.Faker('email')
    birthdate = date(1990, 1, 1)
    reason = 'Test reason'
    action = 'Test action'
