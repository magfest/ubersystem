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


def generate_lottery_test_data(session):
    """Seed a coherent hotel lottery / staff rooming / shift-compliance dataset.

    Foundation rows (hotels, room types, inventory, partition, department, jobs,
    night requirements) are looked up by natural key so re-runs reuse them;
    attendees and their lottery entries are created fresh on every run.
    Returns a list of human-readable summary lines.
    """
    from datetime import datetime, time, timedelta
    from pytz import UTC

    from uber.utils import create_new_hash
    from uber.models import (
        Attendee, AdminAccount, Department, DeptMembership, Job, Shift)
    from uber.models.hotel import (
        LotteryHotel, LotteryRoomType, HotelRoomInventory, InventoryPartition,
        InventoryPartitionBlock, PartitionOwner, LotteryRun, LotteryApplication,
        RoomAssignment, NightShiftRequirement)

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

    date_window = dict(
        earliest_checkin_date=event_start, latest_checkin_date=event_start,
        earliest_checkout_date=event_end, latest_checkout_date=event_end)

    # --- Inventory foundation ---
    hotel = _get_or_create(session, LotteryHotel, name='Test Hotel',
                           defaults={'active': True})
    std_type = _get_or_create(
        session, LotteryRoomType, name='Test Standard Room',
        defaults={'capacity': 4, 'min_capacity': 1, 'is_suite': False})
    suite_type = _get_or_create(
        session, LotteryRoomType, name='Test Suite',
        defaults={'capacity': 6, 'min_capacity': 1, 'is_suite': True})

    std_inv = _get_or_create(
        session, HotelRoomInventory, name='Test Standard Block',
        defaults={'hotel_id': hotel.id, 'room_type_id': std_type.id,
                  'quantity': 25, 'capacity': 4, 'is_suite': False,
                  'price': '$199'})
    suite_inv = _get_or_create(
        session, HotelRoomInventory, name='Test Suite Block',
        defaults={'hotel_id': hotel.id, 'suite_type_id': suite_type.id,
                  'quantity': 5, 'capacity': 6, 'is_suite': True,
                  'price': '$799'})

    # --- Partition + scoped owner ---
    partition = _get_or_create(
        session, InventoryPartition, name='Test Partition',
        defaults={'description': 'Generated test partition', 'active': True})
    _get_or_create(session, InventoryPartitionBlock,
                   partition_id=partition.id, inventory_id=std_inv.id,
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
    summary.append("Partition 'Test Partition' owned by partition-owner@example.com (password: magfest)")

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
        defaults={'start_time': c.EPOCH, 'duration': 480, 'weight': 1, 'slots': 25})
    job_two = _get_or_create(
        session, Job, department_id=dept.id, name='Test Shift Two',
        defaults={'start_time': c.EPOCH + timedelta(days=1), 'duration': 480,
                  'weight': 1, 'slots': 25})

    run = _get_or_create(
        session, LotteryRun, name='Test Lottery Run',
        defaults={'status': c.LOTTERY_AWARDED, 'awarded_at': now})

    def make_attendee(first, last, staff=False, hotel_eligible=False):
        attendee = Attendee(
            first_name=first, last_name=last,
            email=f'{first}.{last}@example.com'.lower(),
            badge_type=c.STAFF_BADGE if staff else c.ATTENDEE_BADGE,
            badge_status=c.COMPLETED_STATUS,
            paid=c.NEED_NOT_PAY if staff else c.HAS_PAID,
            staffing=staff, hotel_eligible=hotel_eligible)
        session.add(attendee)
        session.flush()
        return attendee

    def make_application(attendee, **kwargs):
        params = dict(attendee_id=attendee.id, last_submitted=now,
                      terms_accepted=True, data_policy_accepted=True)
        params.update(kwargs)
        application = LotteryApplication(**params)
        session.add(application)
        session.flush()
        return application

    # (a) Regular attendee: awarded and secured
    att = make_attendee('Awarded', 'Attendee')
    app = make_application(
        att, status=c.AWARDED, entry_type=c.ROOM_ENTRY, cellphone='5551230001',
        hotel_preference=str(hotel.id), room_type_preference=str(std_type.id),
        **date_window)
    session.add(RoomAssignment(
        attendee_id=att.id, inventory_id=std_inv.id, lottery_application_id=app.id,
        lottery_run_id=run.id, assignment_reason=c.LOTTERY_AWARD, status=c.SECURED,
        require_cc=True, assigned_check_in_date=event_start,
        assigned_check_out_date=event_end, cc_token='test-vault-token',
        cc_last_four='4242', cc_card_type='Visa', cc_captured_at=now))
    summary.append('Regular attendee with a secured awarded room')

    # (b) Roommate group: leader + two accepted members sharing one room
    leader = make_attendee('Group', 'Leader')
    leader_app = make_application(
        leader, status=c.AWARDED, entry_type=c.GROUP_ENTRY,
        room_group_name='Test Roommates', hotel_preference=str(hotel.id),
        room_type_preference=str(std_type.id), **date_window)
    members = [make_attendee('Group', 'MemberOne'), make_attendee('Group', 'MemberTwo')]
    for member in members:
        make_application(member, status=c.AWARDED, entry_type=c.GROUP_ENTRY,
                         parent_application_id=leader_app.id,
                         invite_status=c.INVITE_ACCEPTED)
    group_room = RoomAssignment(
        attendee_id=leader.id, inventory_id=std_inv.id,
        lottery_application_id=leader_app.id, lottery_run_id=run.id,
        assignment_reason=c.LOTTERY_AWARD, status=c.ASSIGNED, require_cc=True,
        assigned_check_in_date=event_start, assigned_check_out_date=event_end)
    group_room.occupants = [leader] + members
    session.add(group_room)
    summary.append('Roommate group (leader plus two members) sharing one room')

    # (c) Waitlisted entry: confirmed for a narrower window than requested
    att = make_attendee('Waitlisted', 'Attendee')
    app = make_application(
        att, status=c.AWARDED, entry_type=c.ROOM_ENTRY,
        hotel_preference=str(hotel.id), room_type_preference=str(std_type.id),
        **date_window)
    session.add(RoomAssignment(
        attendee_id=att.id, inventory_id=std_inv.id, lottery_application_id=app.id,
        lottery_run_id=run.id, assignment_reason=c.LOTTERY_AWARD, status=c.ASSIGNED,
        require_cc=True, assigned_check_in_date=event_start + timedelta(days=1),
        assigned_check_out_date=event_end, waitlisted_check_in_date=event_start,
        waitlisted_check_out_date=event_end))
    summary.append('Waitlisted attendee (holding fewer nights than requested)')

    # (d) Staff lottery entry on the master bill
    att = make_attendee('Staff', 'Lottery', staff=True, hotel_eligible=True)
    app = make_application(
        att, status=c.AWARDED, entry_type=c.ROOM_ENTRY, is_staff_entry=True,
        hotel_preference=str(hotel.id), room_type_preference=str(std_type.id),
        **date_window)
    session.add(RoomAssignment(
        attendee_id=att.id, inventory_id=std_inv.id, lottery_application_id=app.id,
        lottery_run_id=run.id, assignment_reason=c.STAFF_AUTO, status=c.SECURED,
        require_cc=False, assigned_check_in_date=event_start,
        assigned_check_out_date=event_end))
    summary.append('Staff lottery entry with a master-bill room')

    # (e) Suite entry
    att = make_attendee('Suite', 'Applicant')
    app = make_application(
        att, status=c.AWARDED, entry_type=c.SUITE_ENTRY,
        hotel_preference=str(hotel.id), suite_type_preference=str(suite_type.id),
        **date_window)
    session.add(RoomAssignment(
        attendee_id=att.id, inventory_id=suite_inv.id, lottery_application_id=app.id,
        lottery_run_id=run.id, assignment_reason=c.LOTTERY_AWARD, status=c.ASSIGNED,
        require_cc=True, assigned_check_in_date=event_start,
        assigned_check_out_date=event_end))
    summary.append('Suite lottery entry with an awarded suite')

    # (f) Hotel-eligible staffer who meets the core-night shift requirement
    att = make_attendee('Compliant', 'Staffer', staff=True, hotel_eligible=True)
    session.add(DeptMembership(attendee_id=att.id, department_id=dept.id))
    session.add(Shift(attendee_id=att.id, job_id=job_one.id))
    session.add(Shift(attendee_id=att.id, job_id=job_two.id))
    session.add(RoomAssignment(
        attendee_id=att.id, inventory_id=std_inv.id, assignment_reason=c.MANUAL,
        status=c.ASSIGNED, require_cc=False, assigned_check_in_date=event_start,
        assigned_check_out_date=event_end, partition_id=partition.id))
    summary.append('Hotel-eligible staffer who meets the shift requirement')

    # (g) Staffer with a room but no shifts: a compliance violation
    att = make_attendee('NonCompliant', 'Staffer', staff=True, hotel_eligible=True)
    session.add(DeptMembership(attendee_id=att.id, department_id=dept.id))
    session.add(RoomAssignment(
        attendee_id=att.id, inventory_id=std_inv.id, assignment_reason=c.MANUAL,
        status=c.ASSIGNED, require_cc=False, assigned_check_in_date=event_start,
        assigned_check_out_date=event_end))
    summary.append('Staffer with a room but no shifts (shift-compliance violation)')

    return summary


@all_renderable()
class Root:
    def index(self):
        return {}

    def generate(self, session, message=''):
        summary = None
        if c.TEST_DATA_GENERATOR_ENABLED and cherrypy.request.method == 'POST':
            try:
                summary = generate_lottery_test_data(session)
                session.commit()
                message = "Generated hotel lottery test data."
            except Exception:
                session.rollback()
                log.error('Test data generation failed', exc_info=True)
                message = 'Test data generation failed; see the logs for details.'
        return {
            'enabled': c.TEST_DATA_GENERATOR_ENABLED,
            'summary': summary,
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
