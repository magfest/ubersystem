import os
import json
import shlex
import time
import sys
import subprocess
import traceback
import csv
import logging
import random
import six
import pypsutil
import cherrypy
import threading
from datetime import datetime

from sqlalchemy.dialects.postgresql.json import JSONB
from pytz import UTC
from sqlalchemy.types import DateTime
from sqlalchemy import text

from uber.config import c
from uber.decorators import all_renderable, csv_file, public, site_mappable
from uber.models import Choice, UniqueList, MultiChoice, Session
from uber.tasks.health import ping

log = logging.getLogger(__name__)


# admin utilities.  should not be used during normal ubersystem operations except by developers / sysadmins


# quick n dirty. don't use for anything real.
def run_shell_cmd(command_line, working_dir=None):
    args = shlex.split(command_line)
    p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=working_dir)
    out, err = p.communicate()
    return out


def run_git_cmd(cmd):
    git = "/usr/bin/git"
    uber_base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    return run_shell_cmd(git + " " + cmd, working_dir=uber_base_dir)


def prepare_model_export(model, filtered_models=None):
    rows = []

    cols = [getattr(model, col.name) for col in model.__table__.columns]
    rows.append([col.name for col in cols])

    for model in filtered_models:
        row = []
        for col in cols:
            if isinstance(col.type, Choice):
                # Choice columns are integers with a single value with an automatic
                # _label property, e.g. the "shirt" column has a "shirt_label"
                # property, so we'll use that.
                row.append(getattr(model, col.name + '_label'))
            elif isinstance(col.type, MultiChoice):
                # MultiChoice columns are comma-separated integer lists with an
                # automatic _labels property which is a list of string labels.
                # So we'll get that and then separate the labels with slashes.
                row.append(' / '.join(getattr(model, col.name + '_labels')))
            elif isinstance(col.type, UniqueList):
                row.append(', '.join(getattr(model, col.name)))
            elif isinstance(col.type, DateTime):
                # Use the empty string if this is null, otherwise use strftime.
                # Also you should fill in whatever actual format you want.
                val = getattr(model, col.name)
                row.append(val.strftime('%Y-%m-%d %H:%M:%S') if val else '')
            elif isinstance(col.type, JSONB):
                row.append(json.dumps(getattr(model, col.name)))
            else:
                # For everything else we'll just dump the value, although we might
                # consider adding more special cases for things like foreign keys.
                row.append(getattr(model, col.name))
        rows.append(row)
    return rows

def _get_thread_current_stacktrace(thread_stack, thread):
    out = []
    status = '[unknown]'
    if thread.native_id != -1:
        status = pypsutil.Process(thread.native_id).status().name
    out.append('\n--------------------------------------------------------------------------')
    out.append('# Thread name: "%s"\n# Python thread.ident: %d\n# Linux Thread PID (TID): %d\n# Run Status: %s'
                % (thread.name, thread.ident, thread.native_id, status))
    for filename, lineno, name, line in traceback.extract_stack(thread_stack):
        out.append('File: "%s", line %d, in %s' % (filename, lineno, name))
        if line:
            out.append('  %s' % (line.strip()))
    return out

def threading_information():
    out = []
    threads_by_id = dict([(thread.ident, thread) for thread in threading.enumerate()])
    for thread_id, thread_stack in sys._current_frames().items():
        thread = threads_by_id.get(thread_id, '')
        out += _get_thread_current_stacktrace(thread_stack, thread)
        if thread.native_id != -1:
            proc = pypsutil.Process(thread.native_id)
            out.append(f"Mem: {proc.memory_info().rss}")
            out.append(f"CPU: {proc.cpu_times().user}")
    return '\n'.join(out)

def general_system_info():
    """
    Print general system info
    TODO:
    - print memory nicer, convert mem to megabytes
    - disk partitions usage,
    - # of open file handles
    - # free inode count
    - # of cherrypy session files
    - # of cherrypy session locks (should be low)
    """
    out = []
    out += ['Mem: ' + repr(pypsutil.virtual_memory().used)]
    out += ['Swap: ' + repr(pypsutil.swap_memory().used)]
    return '\n'.join(out)

def database_pool_information():
    return Session.engine.pool.status()


def _get_or_create(session, model, defaults=None, **lookup):
    instance = session.query(model).filter_by(**lookup).first()
    if instance:
        return instance
    params = dict(lookup)
    if defaults:
        params.update(defaults)
    instance = model(**params)
    session.add(instance)
    session.flush()
    return instance


def generate_lottery_test_data(session, count=40, seed=1337):
    """Seed a hotel lottery / staff rooming / shift-compliance dataset.

    Deterministic and idempotent:
      - Foundation rows (hotels, room types, inventory, partition,
        department, jobs, night requirements, the lottery run) are looked
        up by natural key, so re-runs reuse them.
      - Every generated attendee has a stable email derived from their
        index (lottery-test-NNNN@example.com); an attendee whose email
        already exists is skipped entirely, so re-running never creates
        duplicates. Raising `count` on a later run only adds the new tail.
      - Each persona's attributes come from a per-index RNG seeded with
        a string of (seed, index), so existing personas don't change when count grows.

    `count` is the number of primary bulk personas; roommate-group members
    are created on top of that. A handful of fixed curated scenarios
    (stable emails) always exist for quick manual testing.

    Returns a list of human-readable summary lines.
    """
    import random
    from datetime import datetime, time, timedelta
    from pytz import UTC

    from uber.utils import create_new_hash, RegistrationCode
    from uber.models import (
        Attendee, AdminAccount, Department, DeptMembership, Job, Shift)
    from uber.models.hotel import (
        LotteryHotel, LotteryRoomType, HotelRoomInventory, InventoryNightQuantity,
        InventoryPartition, InventoryPartitionBlock, PartitionOwner, LotteryRun,
        LotteryApplication, RoomAssignment, RoomAssignmentInvite,
        NightShiftRequirement)

    summary = []
    now = datetime.now(UTC)

    event_start = c.EPOCH.date()
    event_end = c.ESCHATON.date()
    if event_end <= event_start:
        event_end = event_start + timedelta(days=1)
    nights = []
    night = event_start
    while night < event_end:
        nights.append(night)
        night += timedelta(days=1)

    full_window = dict(
        earliest_checkin_date=event_start, latest_checkin_date=event_start,
        earliest_checkout_date=event_end, latest_checkout_date=event_end)

    # ------------------------------------------------------------------
    # Inventory foundation: three hotels x several room types, with varied
    # prices, a vault-scoped hotel, a per-night quantity override, and a
    # connector room type chained to the suite type.
    # ------------------------------------------------------------------
    hotels = [
        _get_or_create(session, LotteryHotel, name='Test Hotel',
                       defaults={'active': True, 'export_name': 'test_hotel'}),
        _get_or_create(session, LotteryHotel, name='Test Hotel East',
                       defaults={'active': True, 'export_name': 'test_hotel_east'}),
        _get_or_create(session, LotteryHotel, name='Test Hotel West',
                       defaults={'active': True, 'export_name': 'test_hotel_west'}),
    ]
    std_type = _get_or_create(
        session, LotteryRoomType, name='Test Standard Room',
        defaults={'capacity': 4, 'min_capacity': 1, 'is_suite': False})
    dbl_type = _get_or_create(
        session, LotteryRoomType, name='Test Double Queen',
        defaults={'capacity': 4, 'min_capacity': 2, 'is_suite': False})
    king_type = _get_or_create(
        session, LotteryRoomType, name='Test King Room',
        defaults={'capacity': 2, 'min_capacity': 1, 'is_suite': False})
    suite_type = _get_or_create(
        session, LotteryRoomType, name='Test Suite',
        defaults={'capacity': 6, 'min_capacity': 1, 'is_suite': True})
    connector_type = _get_or_create(
        session, LotteryRoomType, name='Test Connector Room',
        defaults={'capacity': 2, 'min_capacity': 1, 'is_suite': False,
                  'connects_to_type_id': suite_type.id, 'connector_quantity': 1})

    room_types = [std_type, dbl_type, king_type]
    inv_blocks = []       # standard-room inventory across all hotels
    suite_blocks = []     # suite inventory
    connector_blocks = {}  # hotel_id -> connector inventory
    prices = {std_type.id: '$199', dbl_type.id: '$219', king_type.id: '$249'}
    for h_idx, hotel in enumerate(hotels):
        for rt in room_types:
            inv_blocks.append(_get_or_create(
                session, HotelRoomInventory,
                name=f'{hotel.name} - {rt.name.replace("Test ", "")} Block',
                defaults={'hotel_id': hotel.id, 'room_type_id': rt.id,
                          'quantity': 15 + 10 * h_idx, 'capacity': rt.capacity,
                          'is_suite': False, 'price': prices[rt.id],
                          # One hotel gets an explicit vault scope so card
                          # reuse across hotels can be exercised.
                          'vault_reference': ('test_vault_east'
                                              if h_idx == 1 else None)}))
        suite_blocks.append(_get_or_create(
            session, HotelRoomInventory,
            name=f'{hotel.name} - Suite Block',
            defaults={'hotel_id': hotel.id, 'suite_type_id': suite_type.id,
                      'quantity': 4, 'capacity': 6, 'is_suite': True,
                      'price': '$799'}))
        connector_blocks[hotel.id] = _get_or_create(
            session, HotelRoomInventory,
            name=f'{hotel.name} - Connector Block',
            defaults={'hotel_id': hotel.id, 'room_type_id': connector_type.id,
                      'quantity': 4, 'capacity': 2, 'is_suite': False,
                      'price': '$179'})
    # Per-night quantity override on one block (scarce first night).
    _get_or_create(
        session, InventoryNightQuantity, inventory_id=inv_blocks[0].id,
        night_date=event_start, defaults={'quantity': 5})

    # --- Partition + scoped owner ---
    partition = _get_or_create(
        session, InventoryPartition, name='Test Partition',
        defaults={'description': 'Generated test partition', 'active': True})
    _get_or_create(session, InventoryPartitionBlock,
                   partition_id=partition.id, inventory_id=inv_blocks[0].id,
                   defaults={'quantity': 5})

    owner_attendee = session.query(Attendee).filter_by(
        email='partition-owner@example.com').first()
    if not owner_attendee:
        owner_attendee = Attendee(
            first_name='Partition', last_name='Owner',
            email='partition-owner@example.com', badge_type=c.ATTENDEE_BADGE,
            badge_status=c.COMPLETED_STATUS, paid=c.HAS_PAID)
        session.add(owner_attendee)
        session.flush()
    owner_account = session.query(AdminAccount).filter_by(
        attendee_id=owner_attendee.id).first()
    if not owner_account:
        owner_account = AdminAccount(attendee=owner_attendee)
        if not c.SAML_SETTINGS:
            owner_account.hashed = create_new_hash('magfest')
        session.add(owner_account)
        session.flush()
    _get_or_create(
        session, PartitionOwner, admin_account_id=owner_account.id,
        partition_id=partition.id,
        defaults={'can_view_inventory': True, 'can_edit_inventory': True,
                  'can_view_assignments': True, 'can_edit_assignments': True,
                  'can_view_guest_names': True})
    summary.append("Partition 'Test Partition' owned by "
                   "partition-owner@example.com (password: magfest)")

    # --- Shift requirements: setup window + core nights ---
    required_hours = 15
    setup_night = event_start - timedelta(days=1)
    _get_or_create(
        session, NightShiftRequirement, night_date=setup_night,
        defaults={'kind': c.SETUP,
                  'shift_window_start': c.EVENT_TIMEZONE.localize(
                      datetime.combine(setup_night, time(12, 0))),
                  'shift_window_end': c.EVENT_TIMEZONE.localize(
                      datetime.combine(setup_night, time(18, 0)))})
    for night in nights:
        _get_or_create(session, NightShiftRequirement, night_date=night,
                       defaults={'kind': c.CORE,
                                 'required_weighted_hours': required_hours})

    # --- Department + jobs to back shift compliance ---
    dept = _get_or_create(session, Department, name='Test Lottery Department',
                          defaults={'description': 'Generated for lottery test data'})
    job_one = _get_or_create(
        session, Job, department_id=dept.id, name='Test Shift One',
        defaults={'start_time': c.EPOCH, 'duration': 480, 'weight': 1,
                  'slots': max(50, count)})
    job_two = _get_or_create(
        session, Job, department_id=dept.id, name='Test Shift Two',
        defaults={'start_time': c.EPOCH + timedelta(days=1), 'duration': 480,
                  'weight': 1, 'slots': max(50, count)})

    run = _get_or_create(
        session, LotteryRun, name='Test Lottery Run',
        defaults={'status': c.LOTTERY_AWARDED, 'awarded_at': now})

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------
    def make_attendee(first, last, email, staff=False, hotel_eligible=False,
                      cellphone=''):
        """Get-or-create by email. Returns (attendee, created)."""
        existing = session.query(Attendee).filter_by(email=email).first()
        if existing:
            return existing, False
        attendee = Attendee(
            first_name=first, last_name=last, email=email,
            badge_type=c.STAFF_BADGE if staff else c.ATTENDEE_BADGE,
            badge_status=c.COMPLETED_STATUS,
            paid=c.NEED_NOT_PAY if staff else c.HAS_PAID,
            staffing=staff, hotel_eligible=hotel_eligible,
            cellphone=cellphone)
        session.add(attendee)
        session.flush()
        return attendee, True

    def make_application(attendee, **kwargs):
        params = dict(attendee_id=attendee.id, last_submitted=now,
                      terms_accepted=True, data_policy_accepted=True)
        params.update(kwargs)
        application = LotteryApplication(**params)
        session.add(application)
        session.flush()
        return application

    def ranked_prefs(rng, items):
        picks = rng.sample(items, k=rng.randint(1, len(items)))
        return ','.join(str(x.id) for x in picks)

    def make_token(rng):
        return 'TEST-' + ''.join(rng.choice('ABCDEFGHJKMNPQRSTUVWXYZ23456789')
                                 for _ in range(8))

    BILLING = [
        ('123 Test St', 'Rockville', 'MD', '20850', 'United States'),
        ('42 Sample Ave', 'Pittsburgh', 'PA', '15213', 'United States'),
        ('9 Placeholder Blvd', 'Austin', 'TX', '78701', 'United States'),
        ('77 Mock Lane', 'Toronto', 'ON', 'M5V 2T6', 'Canada'),
    ]
    REQUESTS = ['', '', '', 'High floor please', 'Near the elevator',
                'Feather-free bedding', 'Two beds if at all possible',
                'Late checkout if available', 'Quiet room away from parties']
    ADA_REQUESTS = ['Roll-in shower', 'Visual fire alarm',
                    'Close to elevator, limited mobility', 'Service animal']
    GROUP_NAMES = ['Chiptune Crew', 'The Rat Pack', 'Con Crud Survivors',
                   'Pixel Pals', 'Night Owls', 'The Load Bearers',
                   'Save Point', 'Party Wipe', 'Lag Spike', 'The Merge Conflicts']
    FIRSTS = ['Alex', 'Bailey', 'Casey', 'Devon', 'Emery', 'Frankie', 'Gray',
              'Harper', 'Indigo', 'Jules', 'Kai', 'Lane', 'Marlow', 'Noel',
              'Oakley', 'Parker', 'Quinn', 'Reese', 'Sage', 'Tatum', 'Umber',
              'Vesper', 'Wren', 'Xen', 'Yael', 'Zephyr', 'Ash', 'Blair',
              'Cameron', 'Dana', 'Ellis', 'Flynn']
    LASTS = ['Anderson', 'Blackwood', 'Castellanos', 'Duarte', 'Ellison',
             'Fitzgerald', 'Goldberg', 'Huang', 'Ivanova', 'Jimenez',
             'Kowalski', 'Laurent', 'Mbeki', 'Nakamura', 'Okafor', 'Petrov',
             'Quach', 'Rosenberg', 'Silva', 'Tanaka', 'Ueda', 'Vance',
             'Whitfield', 'Xu', 'Yamamoto', 'Zielinski', 'Abara', 'Bishop',
             'Chen', 'Delacroix', 'Eastman', 'Farouk']

    def persona_name(i):
        first = FIRSTS[i % len(FIRSTS)]
        last = LASTS[(i // len(FIRSTS)) % len(LASTS)]
        if i >= len(FIRSTS) * len(LASTS):
            last = f'{last}{i}'
        return first, last

    # ------------------------------------------------------------------
    # Curated scenarios with stable emails: quick manual-testing anchors.
    # Skipped wholesale once their attendee exists.
    # ------------------------------------------------------------------
    curated_created = 0

    att, created = make_attendee('Awarded', 'Attendee', 'awarded.attendee@example.com',
                                 cellphone='5551230001')
    if created:
        app = make_application(
            att, status=c.AWARDED, entry_type=c.ROOM_ENTRY, cellphone='5551230001',
            hotel_preference=str(hotels[0].id), room_type_preference=str(std_type.id),
            **full_window)
        session.add(RoomAssignment(
            attendee_id=att.id, inventory_id=inv_blocks[0].id,
            lottery_application_id=app.id, lottery_run_id=run.id,
            assignment_reason=c.LOTTERY_AWARD, status=c.SECURED, require_cc=True,
            assigned_check_in_date=event_start, assigned_check_out_date=event_end,
            cc_token='test-vault-token', cc_last_four='4242', cc_card_type='Visa',
            cc_captured_at=now, address1='123 Test St', city='Rockville',
            region='MD', zip_code='20850', country='United States'))
        curated_created += 1

    leader, created = make_attendee('Group', 'Leader', 'group.leader@example.com')
    if created:
        leader_app = make_application(
            leader, status=c.AWARDED, entry_type=c.ROOM_ENTRY,
            room_group_name='Test Roommates',
            invite_code=RegistrationCode.generate_random_code(
                LotteryApplication.invite_code),
            hotel_preference=str(hotels[0].id),
            room_type_preference=str(std_type.id), **full_window)
        members = []
        for n, name in enumerate(['MemberOne', 'MemberTwo']):
            member, _ = make_attendee('Group', name,
                                      f'group.member{n + 1}@example.com')
            make_application(member, status=c.AWARDED, entry_type=c.GROUP_ENTRY,
                             parent_application_id=leader_app.id,
                             invite_status=c.INVITE_ACCEPTED)
            members.append(member)
        group_room = RoomAssignment(
            attendee_id=leader.id, inventory_id=inv_blocks[0].id,
            lottery_application_id=leader_app.id, lottery_run_id=run.id,
            assignment_reason=c.LOTTERY_AWARD, status=c.ASSIGNED, require_cc=True,
            assigned_check_in_date=event_start, assigned_check_out_date=event_end)
        group_room.occupants = [leader] + members
        session.add(group_room)
        curated_created += 1

    att, created = make_attendee('Waitlisted', 'Attendee',
                                 'waitlisted.attendee@example.com')
    if created:
        app = make_application(
            att, status=c.AWARDED, entry_type=c.ROOM_ENTRY,
            hotel_preference=str(hotels[0].id),
            room_type_preference=str(std_type.id), **full_window)
        session.add(RoomAssignment(
            attendee_id=att.id, inventory_id=inv_blocks[0].id,
            lottery_application_id=app.id, lottery_run_id=run.id,
            assignment_reason=c.LOTTERY_AWARD, status=c.ASSIGNED, require_cc=True,
            assigned_check_in_date=event_start + timedelta(days=1),
            assigned_check_out_date=event_end,
            waitlisted_check_in_date=event_start,
            waitlisted_check_out_date=event_end, waitlist_started_at=now))
        curated_created += 1

    att, created = make_attendee('Staff', 'Lottery', 'staff.lottery@example.com',
                                 staff=True, hotel_eligible=True)
    if created:
        app = make_application(
            att, status=c.AWARDED, entry_type=c.ROOM_ENTRY, is_staff_entry=True,
            hotel_preference=str(hotels[0].id),
            room_type_preference=str(std_type.id), **full_window)
        session.add(RoomAssignment(
            attendee_id=att.id, inventory_id=inv_blocks[0].id,
            lottery_application_id=app.id, lottery_run_id=run.id,
            assignment_reason=c.STAFF_AUTO, status=c.SECURED, require_cc=False,
            assigned_check_in_date=event_start, assigned_check_out_date=event_end))
        curated_created += 1

    att, created = make_attendee('Suite', 'Applicant', 'suite.applicant@example.com')
    if created:
        app = make_application(
            att, status=c.AWARDED, entry_type=c.SUITE_ENTRY,
            hotel_preference=str(hotels[0].id),
            suite_type_preference=str(suite_type.id), suite_terms_accepted=True,
            **full_window)
        suite_room = RoomAssignment(
            attendee_id=att.id, inventory_id=suite_blocks[0].id,
            lottery_application_id=app.id, lottery_run_id=run.id,
            assignment_reason=c.LOTTERY_AWARD, status=c.ASSIGNED, require_cc=True,
            assigned_check_in_date=event_start, assigned_check_out_date=event_end)
        session.add(suite_room)
        session.flush()
        session.add(RoomAssignment(
            attendee_id=att.id, inventory_id=connector_blocks[hotels[0].id].id,
            lottery_application_id=app.id, lottery_run_id=run.id,
            parent_assignment_id=suite_room.id,
            assignment_reason=c.SUITE_CONNECTOR, status=c.ASSIGNED,
            require_cc=True, assigned_check_in_date=event_start,
            assigned_check_out_date=event_end))
        curated_created += 1

    att, created = make_attendee('Compliant', 'Staffer', 'compliant.staffer@example.com',
                                 staff=True, hotel_eligible=True)
    if created:
        session.add(DeptMembership(attendee_id=att.id, department_id=dept.id))
        session.add(Shift(attendee_id=att.id, job_id=job_one.id))
        session.add(Shift(attendee_id=att.id, job_id=job_two.id))
        session.add(RoomAssignment(
            attendee_id=att.id, inventory_id=inv_blocks[0].id,
            assignment_reason=c.MANUAL, status=c.ASSIGNED, require_cc=False,
            assigned_check_in_date=event_start, assigned_check_out_date=event_end,
            partition_id=partition.id))
        curated_created += 1

    att, created = make_attendee('NonCompliant', 'Staffer',
                                 'noncompliant.staffer@example.com',
                                 staff=True, hotel_eligible=True)
    if created:
        session.add(DeptMembership(attendee_id=att.id, department_id=dept.id))
        session.add(RoomAssignment(
            attendee_id=att.id, inventory_id=inv_blocks[0].id,
            assignment_reason=c.MANUAL, status=c.ASSIGNED, require_cc=False,
            assigned_check_in_date=event_start, assigned_check_out_date=event_end))
        curated_created += 1

    summary.append(f'Curated scenarios: {curated_created} created, '
                   f'{7 - curated_created} already existed')

    # ------------------------------------------------------------------
    # Bulk personas. Each index deterministically derives one persona; an
    # existing email means the persona was made by a previous run and is
    # skipped, so re-runs add nothing and a larger count adds only the tail.
    # ------------------------------------------------------------------
    stats = {'created': 0, 'skipped': 0, 'no_entry': 0, 'partial': 0,
             'complete': 0, 'processed': 0, 'awarded': 0, 'withdrawn': 0,
             'groups': 0, 'members': 0, 'suites': 0, 'connectors': 0,
             'waitlisted': 0, 'cancelled_expired': 0, 'staff': 0,
             'room_invites': 0, 'group_invites': 0}
    priority_keys = [key for key, _ in c.HOTEL_LOTTERY_PRIORITIES_OPTS]

    for i in range(count):
        email = f'lottery-test-{i:04d}@example.com'
        if session.query(Attendee).filter_by(email=email).first():
            stats['skipped'] += 1
            continue

        rng = random.Random(f'{seed}:{i}')
        first, last = persona_name(i)
        staff = rng.random() < 0.15
        cellphone = f'555{rng.randint(1000000, 9999999)}'
        att, _ = make_attendee(first, last, email, staff=staff,
                               hotel_eligible=staff, cellphone=cellphone)
        stats['created'] += 1
        if staff:
            stats['staff'] += 1

        # Entry lifecycle distribution.
        roll = rng.random()
        if roll < 0.08:
            stats['no_entry'] += 1        # eligible, never entered
            continue

        is_suite_entry = rng.random() < 0.15
        entry_type = c.SUITE_ENTRY if is_suite_entry else c.ROOM_ENTRY
        ci = event_start + timedelta(days=rng.randint(0, 2))
        co = event_end - timedelta(days=rng.randint(0, 2))
        if co <= ci:
            co = ci + timedelta(days=1)
        wants_ada = rng.random() < 0.08
        app_kwargs = dict(
            entry_type=entry_type, is_staff_entry=staff, cellphone=cellphone,
            earliest_checkin_date=ci, latest_checkin_date=ci,
            earliest_checkout_date=co, latest_checkout_date=co,
            hotel_preference=ranked_prefs(rng, hotels),
            wants_ada=wants_ada,
            ada_requests=rng.choice(ADA_REQUESTS) if wants_ada else '',
            guarantee_policy_accepted=True)
        if is_suite_entry:
            app_kwargs['suite_type_preference'] = str(suite_type.id)
            app_kwargs['suite_terms_accepted'] = True
            app_kwargs['room_opt_out'] = rng.random() < 0.3
            app_kwargs['room_type_preference'] = ranked_prefs(rng, room_types)
        else:
            app_kwargs['room_type_preference'] = ranked_prefs(rng, room_types)
        if priority_keys:
            picks = rng.sample(priority_keys, k=len(priority_keys))
            app_kwargs['selection_priorities'] = ','.join(picks)

        if roll < 0.18:
            make_application(att, status=c.PARTIAL, entry_started=now,
                             **app_kwargs)
            stats['partial'] += 1
            continue
        if roll < 0.24:
            make_application(att, status=c.WITHDRAWN, **app_kwargs)
            stats['withdrawn'] += 1
            continue
        if roll < 0.46:
            make_application(att, status=c.COMPLETE, **app_kwargs)
            stats['complete'] += 1
            continue
        if roll < 0.54:
            make_application(att, status=c.PROCESSED, lottery_run_id=run.id,
                             **app_kwargs)
            stats['processed'] += 1
            continue

        # Awarded (the rest): create the application plus room assignment(s).
        is_leader = not is_suite_entry and rng.random() < 0.18
        if is_leader:
            app_kwargs['room_group_name'] = (
                f'{rng.choice(GROUP_NAMES)} {i:04d}')
            app_kwargs['invite_code'] = RegistrationCode.generate_random_code(
                LotteryApplication.invite_code)
        app = make_application(att, status=c.AWARDED, **app_kwargs)
        stats['awarded'] += 1

        hotel = rng.choice(hotels)
        if is_suite_entry:
            inv = next(b for b in suite_blocks if b.hotel_id == hotel.id)
            stats['suites'] += 1
        else:
            hotel_blocks = [b for b in inv_blocks if b.hotel_id == hotel.id]
            inv = rng.choice(hotel_blocks)

        status_roll = rng.random()
        if status_roll < 0.45:
            ra_status = c.SECURED
        elif status_roll < 0.80:
            ra_status = c.ASSIGNED
        elif status_roll < 0.90:
            ra_status = c.CANCELLED
        else:
            ra_status = c.EXPIRED

        require_cc = not (staff and rng.random() < 0.7)
        ra = RoomAssignment(
            attendee_id=att.id, inventory_id=inv.id,
            lottery_application_id=app.id, lottery_run_id=run.id,
            assignment_reason=c.LOTTERY_AWARD, status=ra_status,
            require_cc=require_cc,
            assigned_check_in_date=ci, assigned_check_out_date=co,
            special_requests=rng.choice(REQUESTS),
            booking_url=(f'https://booking.example.com/test/{i:04d}'
                         if rng.random() < 0.6 else ''))
        if ra_status == c.SECURED:
            addr = rng.choice(BILLING)
            ra.cc_token = f'test-vault-token-{i:04d}'
            ra.cc_last_four = f'{rng.randint(0, 9999):04d}'
            ra.cc_card_type = rng.choice(['Visa', 'Mastercard', 'Amex', 'Discover'])
            ra.cc_captured_at = now
            (ra.address1, ra.city, ra.region, ra.zip_code, ra.country) = addr
            if rng.random() < 0.4:
                ra.hotel_rewards_number = f'HR{rng.randint(10000000, 99999999)}'
            if rng.random() < 0.5:
                ra.hotel_confirmation_number = f'CONF{rng.randint(100000, 999999)}'
        elif ra_status == c.ASSIGNED and require_cc:
            # Some awaiting-card rooms carry a deadline (future and past,
            # so the expiry cron has something to chew on).
            if rng.random() < 0.6:
                ra.deposit_cutoff_date = (
                    now.date() + timedelta(days=rng.randint(-2, 14)))
        if ra_status in (c.CANCELLED, c.EXPIRED):
            stats['cancelled_expired'] += 1
        # Waitlist: ~20% of live rooms hold fewer nights than requested.
        if ra.is_live and rng.random() < 0.2 and (co - ci).days >= 2:
            ra.assigned_check_in_date = ci + timedelta(days=1)
            ra.waitlisted_check_in_date = ci
            ra.waitlisted_check_out_date = co
            ra.waitlist_started_at = now - timedelta(hours=rng.randint(1, 72))
            stats['waitlisted'] += 1
        session.add(ra)
        session.flush()

        # Suite awards sometimes include a connector child room.
        if is_suite_entry and ra.is_live and rng.random() < 0.5:
            session.add(RoomAssignment(
                attendee_id=att.id, inventory_id=connector_blocks[hotel.id].id,
                lottery_application_id=app.id, lottery_run_id=run.id,
                parent_assignment_id=ra.id, assignment_reason=c.SUITE_CONNECTOR,
                status=ra_status, require_cc=require_cc,
                assigned_check_in_date=ra.assigned_check_in_date,
                assigned_check_out_date=co))
            stats['connectors'] += 1

        # Roommate groups: 1-3 members, plus occasionally a pending
        # email invite (application-level) still waiting on an answer.
        if is_leader and ra.is_live:
            stats['groups'] += 1
            occupants = [att]
            for n in range(rng.randint(1, 3)):
                m_email = f'lottery-test-{i:04d}-m{n}@example.com'
                member, m_created = make_attendee(
                    *persona_name(count + i * 3 + n), m_email)
                if m_created:
                    make_application(
                        member, status=c.AWARDED, entry_type=c.GROUP_ENTRY,
                        parent_application_id=app.id,
                        invite_status=c.INVITE_ACCEPTED)
                occupants.append(member)
                stats['members'] += 1
            ra.occupants = occupants
            session.add(ra)
            if rng.random() < 0.4:
                p_email = f'lottery-test-{i:04d}-pending@example.com'
                pending, p_created = make_attendee(
                    *persona_name(count * 2 + i), p_email)
                if p_created:
                    make_application(
                        pending, status=c.COMPLETE, entry_type=c.ROOM_ENTRY,
                        invite_status=c.INVITE_PENDING,
                        invite_token=make_token(rng),
                        invited_by_id=app.id,
                        invite_expires_at=now + timedelta(days=7))
                    stats['group_invites'] += 1

        # Pending per-room occupant invites on rooms with headroom.
        if ra.is_live and not is_leader and rng.random() < 0.15:
            session.add(RoomAssignmentInvite(
                room_assignment_id=ra.id, invite_token=make_token(rng),
                email=(f'lottery-test-{i:04d}-invitee@example.com'
                       if rng.random() < 0.5 else None)))
            stats['room_invites'] += 1

        # Staff with live rooms join the department; 60% work their
        # shifts (compliant), the rest trip the compliance report.
        if staff and ra.is_live:
            session.add(DeptMembership(attendee_id=att.id, department_id=dept.id))
            if rng.random() < 0.6:
                session.add(Shift(attendee_id=att.id, job_id=job_one.id))
                session.add(Shift(attendee_id=att.id, job_id=job_two.id))

    summary.append(
        f"Bulk personas: {stats['created']} created, {stats['skipped']} "
        f"already existed (re-run safe); seed {seed}")
    summary.append(
        f"Entries - no entry: {stats['no_entry']}, partial: {stats['partial']}, "
        f"complete: {stats['complete']}, processed: {stats['processed']}, "
        f"awarded: {stats['awarded']}, withdrawn: {stats['withdrawn']}")
    summary.append(
        f"Rooms - suites: {stats['suites']} ({stats['connectors']} with "
        f"connectors), waitlisted: {stats['waitlisted']}, cancelled/expired: "
        f"{stats['cancelled_expired']}")
    summary.append(
        f"People - staff: {stats['staff']}, roommate groups: {stats['groups']} "
        f"({stats['members']} members), pending group invites: "
        f"{stats['group_invites']}, pending room invites: {stats['room_invites']}")
    return summary


@all_renderable()
class Root:
    def index(self):
        return {}

    def generate(self, session, message='', csrf_token=None,
                 count='40', seed='1337'):
        summary = None
        try:
            count = max(0, min(1000, int(count)))
        except (TypeError, ValueError):
            count = 40
        try:
            seed = int(seed)
        except (TypeError, ValueError):
            seed = 1337
        if c.TEST_DATA_GENERATOR_ENABLED and cherrypy.request.method == 'POST':
            from uber.utils import check_csrf
            check_csrf(csrf_token)
            try:
                summary = generate_lottery_test_data(session, count=count,
                                                     seed=seed)
                session.commit()
                message = "Generated hotel lottery test data."
            except Exception:
                session.rollback()
                log.error('Test data generation failed', exc_info=True)
                message = 'Test data generation failed; see the logs for details.'
        return {
            'enabled': c.TEST_DATA_GENERATOR_ENABLED,
            'summary': summary,
            'count': count,
            'seed': seed,
            'message': message,
        }

    # this is quick and dirty.
    # print out some info relevant to developers such as what the current version of ubersystem this is,
    # which branch it is, etc.
    def gitinfo(self):
        git_branch_name = run_git_cmd("rev-parse --abbrev-ref HEAD")
        git_current_sha = run_git_cmd("rev-parse --verify HEAD")
        last_commit_log = run_git_cmd("show --name-status")
        git_status = run_git_cmd("status")

        return {
            'git_branch_name': git_branch_name,
            'git_current_sha': git_current_sha,
            'last_commit_log': last_commit_log,
            'git_status': git_status
        }

    def dump_diagnostics(self):
        out = ''
        for func in [general_system_info, threading_information, database_pool_information]:
            out += '--------- {} ---------\n{}\n\n\n'.format(func.__name__.replace('_', ' ').upper(), func())
        return {
            'diagnostics_data': out,
        }

    def csv_import(self, message='', all_instances=None):
        return {
            'message': message,
            'tables': sorted(model.__name__ for model in Session.all_models()),
            'attendees': all_instances
        }

    def import_model(self, session, model_import, selected_model=''):
        model = Session.resolve_model(selected_model)
        message = ''

        cols = {col.name: getattr(model, col.name) for col in model.__table__.columns}
        result = csv.DictReader(model_import.file.read().decode('utf-8').split('\n'))
        id_list = []

        for row in result:
            if 'id' in row:
                id = row.pop('id')  # id needs special treatment

                try:
                    # get the instance if it already exists
                    model_instance = getattr(session, selected_model)(id, allow_invalid=True)
                except Exception:
                    session.rollback()
                    # otherwise, make a new one and add it to the session for when we commit
                    model_instance = model()
                    session.add(model_instance)
            else:
                model_instance = model()
                session.add(model_instance)

            for colname, val in row.items():
                col = cols[colname]
                setattr(model_instance, colname, model_instance.coerce_column_data(col, val))

            id_list.append(model_instance.id)

        try:
            session.commit()
        except Exception:
            log.error('ImportError', exc_info=True)
            session.rollback()
            message = 'Import unsuccessful'

        all_instances = session.query(model).filter(model.id.in_(id_list)).all() if id_list else None

        return self.csv_import(message, all_instances)

    @site_mappable
    def csv_export(self, message='', **params):
        if 'model' in params:
            self.export_model(selected_model=params['model'])

        return {
            'message': message,
            'tables': sorted(model.__name__ for model in Session.all_models())
        }

    @csv_file
    def export_model(self, out, session, selected_model=''):
        model = Session.resolve_model(selected_model)
        rows = prepare_model_export(model, filtered_models=session.query(model).all())
        for row in rows:
            out.writerow(row)

    @public
    def health(self, session):
        cherrypy.response.headers["Access-Control-Allow-Origin"] = "*"
        cherrypy.session.load()

        read_count = cherrypy.session.get("read_count", default=0)
        read_count += 1
        cherrypy.session["read_count"] = read_count
        session_commit_time = -time.perf_counter()
        cherrypy.session.save()
        session_commit_time += time.perf_counter()

        db_read_time = -time.perf_counter()
        session.execute(text('SELECT 1'))
        db_read_time += time.perf_counter()

        return json.dumps({
            'server_current_timestamp': int(datetime.now(UTC).timestamp()),
            'session_read_count': read_count,
            'session_commit_time': session_commit_time,
            'db_read_time': db_read_time,
            'db_status': Session.engine.pool.status(),
        })
