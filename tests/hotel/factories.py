"""In-session factory helpers for the hotel domain-layer tests.

Everything is added to the given session and FLUSHED (never committed);
the per-test `session` fixture rolls the whole transaction back. The
construction patterns mirror uber.site_sections.devtools's
generate_lottery_test_data, minus the idempotency machinery.
"""

import itertools
import uuid
from datetime import date, timedelta

from uber.config import c

_counter = itertools.count(1)

# Arbitrary but stable night grid for capacity/waitlist scenarios. The
# domain code takes explicit dates everywhere, so these need not match the
# configured event dates.
N = [date(2026, 1, 5) + timedelta(days=i) for i in range(10)]


def _tag(prefix):
    return f'{prefix}-{next(_counter)}-{uuid.uuid4().hex[:8]}'


def make_attendee(session, first='Hotel', last=None, **overrides):
    from uber.models import Attendee

    params = dict(
        first_name=first,
        last_name=last or f'Tester{next(_counter)}',
        email=f'{_tag("hotel-test")}@example.com',
        badge_type=c.ATTENDEE_BADGE,
        badge_status=c.COMPLETED_STATUS,
        paid=c.HAS_PAID,
    )
    params.update(overrides)
    attendee = Attendee(**params)
    session.add(attendee)
    session.flush()
    return attendee


def make_hotel(session, name=None, **overrides):
    from uber.models.hotel import LotteryHotel

    params = dict(name=name or _tag('Test Hotel'), active=True)
    params.update(overrides)
    hotel = LotteryHotel(**params)
    session.add(hotel)
    session.flush()
    return hotel


def make_room_type(session, name=None, capacity=4, min_capacity=1,
                   is_suite=False, **overrides):
    from uber.models.hotel import LotteryRoomType

    params = dict(name=name or _tag('Test Room Type'), capacity=capacity,
                  min_capacity=min_capacity, is_suite=is_suite, active=True)
    params.update(overrides)
    room_type = LotteryRoomType(**params)
    session.add(room_type)
    session.flush()
    return room_type


def make_inventory(session, hotel, room_type=None, quantity=10, capacity=4,
                   min_capacity=1, is_suite=False, **overrides):
    from uber.models.hotel import HotelRoomInventory

    params = dict(
        hotel_id=hotel.id,
        quantity=quantity,
        capacity=capacity,
        min_capacity=min_capacity,
        is_suite=is_suite,
        active=True,
        name=_tag('Test Block'),
    )
    if room_type is not None:
        if is_suite:
            params['suite_type_id'] = room_type.id
        else:
            params['room_type_id'] = room_type.id
    params.update(overrides)
    inv = HotelRoomInventory(**params)
    session.add(inv)
    session.flush()
    return inv


def set_night_quantity(session, inventory, night, quantity):
    from uber.models.hotel import InventoryNightQuantity

    nq = InventoryNightQuantity(inventory_id=inventory.id, night_date=night,
                                quantity=quantity)
    session.add(nq)
    session.flush()
    session.refresh(inventory)
    return nq


def make_partition(session, name=None, **overrides):
    from uber.models.hotel import InventoryPartition

    params = dict(name=name or _tag('Test Partition'), active=True)
    params.update(overrides)
    partition = InventoryPartition(**params)
    session.add(partition)
    session.flush()
    return partition


def make_partition_block(session, partition, inventory, quantity):
    from uber.models.hotel import InventoryPartitionBlock

    block = InventoryPartitionBlock(partition_id=partition.id,
                                    inventory_id=inventory.id,
                                    quantity=quantity)
    session.add(block)
    session.flush()
    return block


def make_run(session, **overrides):
    from uber.models.hotel import LotteryRun

    params = dict(name=_tag('Test Run'), status=c.LOTTERY_AWARDED)
    params.update(overrides)
    run = LotteryRun(**params)
    session.add(run)
    session.flush()
    return run


def make_application(session, attendee, status=None, **overrides):
    from uber.models.hotel import LotteryApplication

    params = dict(attendee_id=attendee.id,
                  status=status if status is not None else c.COMPLETE,
                  terms_accepted=True, data_policy_accepted=True)
    params.update(overrides)
    app = LotteryApplication(**params)
    session.add(app)
    session.flush()
    return app


def make_assignment(session, attendee, inventory=None, status=None,
                    check_in=None, check_out=None, **overrides):
    from uber.models.hotel import RoomAssignment

    params = dict(
        attendee_id=attendee.id,
        inventory_id=inventory.id if inventory is not None else None,
        status=status if status is not None else c.ASSIGNED,
        assignment_reason=c.MANUAL,
        require_cc=True,
        assigned_check_in_date=check_in,
        assigned_check_out_date=check_out,
    )
    params.update(overrides)
    ra = RoomAssignment(**params)
    session.add(ra)
    session.flush()
    return ra
