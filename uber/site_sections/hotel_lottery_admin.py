import base64
import pycountry
import cherrypy
import logging
import random
import math
from copy import deepcopy
from collections import defaultdict
from datetime import date, datetime, timedelta
from pytz import UTC
from dateutil import parser as dateparser
import sqlalchemy as sa
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import joinedload
from sqlalchemy.types import String
from ortools.linear_solver import pywraplp

from uber.config import c
from uber.custom_tags import datetime_local_filter
from uber.decorators import all_renderable, log_pageview, ajax, xlsx_file, csv_file, multifile_zipfile, render
from uber.errors import HTTPRedirect
from uber.forms import load_forms
from uber.models import Attendee, Group, LotteryApplication, Email, Tracking, PageViewTracking
from uber.models.hotel import (HotelRoomInventory, InventoryNightQuantity, InventoryPartition,
                               InventoryPartitionBlock, LotteryRun, HotelExportLog, LotteryHotel, LotteryRoomType)
from uber.tasks.email import send_email
from uber.utils import Order, get_page, localized_now, validate_model, get_age_from_birthday, normalize_email_legacy

log = logging.getLogger(__name__)

def _search(session, text):
    applications = session.query(LotteryApplication)

    terms = text.split()
    if len(terms) == 1 and terms[0].isdigit():
        if len(terms[0]) == 10:
            return applications.filter(or_(LotteryApplication.confirmation_num == terms[0])), ''

    check_list = []

    # Skip columns that will raise unexpected applications
    skip_columns = {'id', 'parent_application_id', 'assigned_inventory_id',
                    'lottery_run_id', 'former_parent_id'}
    for attr in [col for col in LotteryApplication.__table__.columns if isinstance(col.type, String)]:
        if attr.name not in skip_columns:
            check_list.append(attr.ilike('%' + text + '%'))

    # Search by hotel name through inventory (single joined query)
    matching_inventory_ids = set()
    hotel_matches = session.query(HotelRoomInventory.id).join(
        LotteryHotel, HotelRoomInventory.hotel_id == LotteryHotel.id
    ).filter(LotteryHotel.name.ilike('%' + text + '%')).all()
    matching_inventory_ids.update(str(row[0]) for row in hotel_matches)

    rt_matches = session.query(HotelRoomInventory.id).join(
        LotteryRoomType, or_(
            HotelRoomInventory.room_type_id == LotteryRoomType.id,
            HotelRoomInventory.suite_type_id == LotteryRoomType.id,
        )
    ).filter(LotteryRoomType.name.ilike('%' + text + '%')).all()
    matching_inventory_ids.update(str(row[0]) for row in rt_matches)

    if matching_inventory_ids:
        check_list.append(LotteryApplication.assigned_inventory_id.in_(matching_inventory_ids))

    for col_name in ['entry_type', 'status']:
        col = getattr(LotteryApplication, col_name).type
        label_list = [choice for choice in col.choices.values()]
        for label in label_list:
            if text.lower() in label.lower():
                check_list.append(getattr(LotteryApplication, col_name) == col.convert_if_label(label))

    if not check_list:
        return applications.filter(sa.false()), 'No matches found.'

    return applications.filter(or_(*check_list)), ''


def _partition_capacity(session, inv, night, partition_id):
    """Compute the effective capacity and assigned count for a block/night respecting partitions.

    If partition_id is set, the capacity is the partition's allocation for this block and only
    same-partition assignments count. If partition_id is None, the capacity is the block's total
    minus all partition allocations, and only non-partitioned assignments count.

    Returns (capacity, assigned_count, open_slots).
    """
    nq_map = inv.night_quantity_map
    block_qty = nq_map.get(night, inv.quantity) if nq_map else inv.quantity

    if partition_id:
        # Partitioned: capacity = partition allocation for this block
        pb = session.query(InventoryPartitionBlock).filter_by(
            partition_id=partition_id, inventory_id=inv.id).first()
        capacity = min(pb.quantity, block_qty) if pb else 0

        assigned_count = session.query(LotteryApplication).filter(
            LotteryApplication.assigned_inventory_id == str(inv.id),
            LotteryApplication.partition_id == partition_id,
            LotteryApplication.status.in_(c.HOTEL_LOTTERY_AWARD_STATUSES),
            LotteryApplication.entry_type != c.GROUP_ENTRY,
            LotteryApplication.assigned_check_in_date <= night,
            LotteryApplication.assigned_check_out_date > night,
        ).count()
    else:
        # Non-partitioned: capacity = block total minus all partition allocations
        total_partitioned = session.query(func.coalesce(func.sum(InventoryPartitionBlock.quantity), 0)).filter(
            InventoryPartitionBlock.inventory_id == str(inv.id),
        ).scalar()
        capacity = max(0, block_qty - total_partitioned)

        assigned_count = session.query(LotteryApplication).filter(
            LotteryApplication.assigned_inventory_id == str(inv.id),
            LotteryApplication.partition_id == None,
            LotteryApplication.status.in_(c.HOTEL_LOTTERY_AWARD_STATUSES),
            LotteryApplication.entry_type != c.GROUP_ENTRY,
            LotteryApplication.assigned_check_in_date <= night,
            LotteryApplication.assigned_check_out_date > night,
        ).count()

    return capacity, assigned_count, max(0, capacity - assigned_count)


def _fulfill_waitlist(session, inventory_id=None, night_date=None):
    """Process waitlist by extending assigned dates for randomly selected eligible attendees.

    Waitlist demand is derived from the delta between requested dates (earliest_checkin_date /
    latest_checkout_date) and assigned dates (assigned_check_in_date / assigned_check_out_date)
    on SECURED applications.

    Args:
        inventory_id: If provided, only process this inventory block.
        night_date: If provided, only process this specific night.
    """
    total_fulfilled = 0
    total_skipped_locked = 0
    fulfilled_app_set = set()

    # Determine which (block, night) pairs to process
    if inventory_id and night_date:
        pairs_to_process = [(inventory_id, night_date)]
    else:
        # Find all blocks with SECURED apps that have waitlist demand
        waitlist_apps = session.query(LotteryApplication).filter(
            LotteryApplication.status == c.SECURED,
            LotteryApplication.entry_type != c.GROUP_ENTRY,
            LotteryApplication.assigned_inventory_id != None,
        ).all()

        pairs = set()
        for app in waitlist_apps:
            block_id = str(app.assigned_inventory_id)
            if inventory_id and block_id != str(inventory_id):
                continue
            # Pre-checkin waitlist nights
            if app.earliest_checkin_date and app.assigned_check_in_date:
                d = app.earliest_checkin_date
                while d < app.assigned_check_in_date:
                    pairs.add((block_id, d))
                    d += timedelta(days=1)
            # Post-checkout waitlist nights
            if app.latest_checkout_date and app.assigned_check_out_date:
                d = app.assigned_check_out_date
                while d < app.latest_checkout_date:
                    pairs.add((block_id, d))
                    d += timedelta(days=1)
        pairs_to_process = sorted(pairs, key=lambda p: p[1])

    for block_id, night in pairs_to_process:
        inv = session.query(HotelRoomInventory).get(block_id)
        if not inv:
            continue

        # Get all distinct partition_ids for candidates on this block
        candidate_partitions = set()
        all_candidates = session.query(LotteryApplication).filter(
            LotteryApplication.assigned_inventory_id == block_id,
            LotteryApplication.status == c.SECURED,
            LotteryApplication.entry_type != c.GROUP_ENTRY,
            LotteryApplication.export_locked == False,
        ).all()

        for app in all_candidates:
            has_demand = False
            if (app.earliest_checkin_date and app.assigned_check_in_date
                    and app.earliest_checkin_date < app.assigned_check_in_date):
                has_demand = True
            if (app.latest_checkout_date and app.assigned_check_out_date
                    and app.latest_checkout_date > app.assigned_check_out_date):
                has_demand = True
            if has_demand:
                candidate_partitions.add(app.partition_id)

        skipped_locked = len([a for a in session.query(LotteryApplication).filter(
            LotteryApplication.assigned_inventory_id == block_id,
            LotteryApplication.status == c.SECURED,
            LotteryApplication.entry_type != c.GROUP_ENTRY,
            LotteryApplication.export_locked == True,
        ).all()])
        total_skipped_locked += skipped_locked

        # Process each partition separately (including None for non-partitioned)
        for part_id in candidate_partitions:
            # Loop to handle cascading adjacency (capped to prevent infinite loops)
            max_iterations = 500
            for _iteration in range(max_iterations):
                capacity, assigned_count, open_slots = _partition_capacity(session, inv, night, part_id)
                if open_slots <= 0:
                    break

                # Find eligible apps in this partition
                eligible = []
                part_filter = (LotteryApplication.partition_id == part_id) if part_id else (LotteryApplication.partition_id == None)
                candidates = session.query(LotteryApplication).filter(
                    LotteryApplication.assigned_inventory_id == block_id,
                    LotteryApplication.status == c.SECURED,
                    LotteryApplication.entry_type != c.GROUP_ENTRY,
                    LotteryApplication.export_locked == False,
                    part_filter,
                ).all()

                for app in candidates:
                    if (app.earliest_checkin_date and app.assigned_check_in_date
                            and night < app.assigned_check_in_date
                            and night >= app.earliest_checkin_date
                            and night == app.assigned_check_in_date - timedelta(days=1)):
                        eligible.append(('checkin', app))
                    elif (app.latest_checkout_date and app.assigned_check_out_date
                            and night >= app.assigned_check_out_date
                            and night < app.latest_checkout_date
                            and night == app.assigned_check_out_date):
                        eligible.append(('checkout', app))

                if not eligible:
                    break

                selected = random.sample(eligible, min(open_slots, len(eligible)))
                if not selected:
                    break

                for direction, app in selected:
                    if direction == 'checkin':
                        app.assigned_check_in_date = night
                    else:
                        app.assigned_check_out_date = night + timedelta(days=1)

                    for member in app.group_members:
                        member.assigned_check_in_date = app.assigned_check_in_date
                        member.assigned_check_out_date = app.assigned_check_out_date
                        session.add(member)

                    session.add(app)
                    total_fulfilled += 1
                    fulfilled_app_set.add(app)

                session.flush()

    session.commit()

    # Send notification emails for fulfilled apps
    for app in fulfilled_app_set:
        if app.attendee:
            send_email.delay(
                sender=c.HOTEL_LOTTERY_EMAIL,
                to=app.attendee.email,
                subject=f'{c.EVENT_NAME} Hotel Lottery - Room Dates Updated',
                body=render('emails/hotel/waitlist_fulfilled.html', {
                    'app': app,
                }),
                model=app.attendee.to_dict() if hasattr(app.attendee, 'to_dict') else str(app.attendee.id),
            )

    return {
        "success": True,
        "fulfilled": total_fulfilled,
        "skipped_locked": total_skipped_locked,
        "message": f"Fulfilled {total_fulfilled} waitlist entries." + (
            f" Skipped {total_skipped_locked} locked entries." if total_skipped_locked else "")
    }


def weight_entry(entry, hotel_room, base_weight):
    """Takes a lottery entry and a hotel room and returns an arbitrary score for how likely that applicant
        should be to get that particular room.
    """
    weight = 0

    # Give 10 points for being the first choice hotel, 9 points for the second, etc
    hotel_choice_rank = 10 - entry["hotels"].index(hotel_room["hotel_id"])
    weight += hotel_choice_rank

    # Give 10 points for being the first choice room type, 9 points for the second, etc
    try:
        room_type_rank = 10 - entry["room_types"].index(hotel_room["room_type"])
        assert room_type_rank >= 0
        weight += room_type_rank
    except ValueError:
        # room types are optional, so we need to figure out how much weight to give people who don't choose any
        weight += 9 # Probably fine?

    return weight + base_weight

def solve_lottery(applications, hotel_rooms, lottery_type=c.ROOM_ENTRY):
    """Takes a set of hotel_rooms and applications and assigns the hotel_rooms mostly randomly.
        Parameters:
        applications List[Application]: Iterable set of Application objects to assign
        hotel_rooms  List[hotels]: Iterable set of hotel rooms, represented as dictionaries with the following keys:
        * id: HotelRoomInventory UUID (inventory block ID)
        * hotel_id: LotteryHotel UUID
        * capacity: int
        * min_capacity: int
        * room_type: LotteryRoomType UUID
        * quantity: int (default/fallback quantity)
        * night_quantities: dict of {date_iso: quantity} for per-night limits

        Returns Dict[Applications -> inventory_id]: A mapping of Application.id -> inventory_block_id or None if it failed
    """
    random.shuffle(applications)
    solver = pywraplp.Solver.CreateSolver("SAT")
    solver.SetSolverSpecificParametersAsString("log_search_progress: true")

    # Collect all nights across all inventory blocks
    all_nights = set()
    for hotel_room in hotel_rooms:
        hotel_room["constraints"] = []
        if hotel_room.get("night_quantities"):
            all_nights.update(hotel_room["night_quantities"].keys())

    entries = {}
    for app in applications:
        if app.entry_type == lottery_type or (lottery_type == c.ROOM_ENTRY and
                                              app.entry_type == c.SUITE_ENTRY and
                                              app.room_opt_out is False):
            if lottery_type == c.ROOM_ENTRY:
                entry = {
                    "members": [app],
                    "hotels": app.hotel_preference.split(","),
                    "room_types": app.room_type_preference.split(","),
                    "constraints": [],
                    "check_in": app.earliest_checkin_date,
                    "check_out": app.latest_checkout_date,
                }
            elif lottery_type == c.SUITE_ENTRY:
                entry = {
                    "members": [app],
                    "hotels": app.hotel_preference.split(","),
                    "room_types": app.suite_type_preference.split(","),
                    "constraints": [],
                    "check_in": app.earliest_checkin_date,
                    "check_out": app.latest_checkout_date,
                }
            entries[app.id] = entry

    for app in applications:
        if app.parent_application and app.parent_application.id in entries:
            entries[app.parent_application.id]["members"].append(app)

    for app_id, entry in entries.items():
        # Bias weights based on group weights
        base_weight = 0
        if random.random() < c.HOTEL_LOTTERY["weights"][f"group_weight_{len(entry['members'])}"]:
            base_weight = c.HOTEL_LOTTERY["weights"][f"group_base_{len(entry['members'])}"]

        for hotel_room in hotel_rooms:
            if hotel_room["hotel_id"] in entry["hotels"] and hotel_room["room_type"] in entry["room_types"] and (hotel_room["min_capacity"] <= len(entry["members"]) <= hotel_room["capacity"]):
                weight = weight_entry(entry, hotel_room, base_weight)

                # Each constraint is a tuple of (BoolVar(), weight, hotel_room)
                constraint = solver.BoolVar(f'{app_id}_assigned_to_{hotel_room["id"]}')
                entry["constraints"].append((constraint, weight, hotel_room))
                hotel_room["constraints"].append((constraint, entry))

    # Set up constraints
    if all_nights:
        # Per-night capacity constraints
        for hotel_room in hotel_rooms:
            if not hotel_room["constraints"]:
                continue
            nq = hotel_room.get("night_quantities", {})
            for night_iso in sorted(all_nights):
                night_qty = nq.get(night_iso, 0)
                if night_qty <= 0:
                    continue
                night_date = date.fromisoformat(night_iso)
                # Only count entries whose date range covers this night
                night_vars = []
                for constraint_var, entry in hotel_room["constraints"]:
                    if entry["check_in"] and entry["check_out"] and entry["check_in"] <= night_date < entry["check_out"]:
                        night_vars.append(constraint_var)
                if night_vars:
                    solver.Add(sum(night_vars) <= night_qty)
    else:
        # Fallback: single quantity constraint (no per-night data)
        for hotel_room in hotel_rooms:
            if hotel_room["constraints"]:
                constraint_vars = [cv for cv, _ in hotel_room["constraints"]]
                print(f"hotel_room {hotel_room['name']} constraints {len(constraint_vars)}, {hotel_room['quantity']}: {type(hotel_room['quantity'])}", flush=True)
                solver.Add(sum(constraint_vars) <= hotel_room["quantity"])

    ## Only allow each group to have one room
    for app, entry in entries.items():
        solver.Add(sum([x[0] for x in entry["constraints"]]) <= 1)

    # Set up Objective function
    objective = solver.Objective()
    for app, entry in entries.items():
        for is_assigned, weight, hotel_room in entry["constraints"]:
            objective.SetCoefficient(is_assigned, weight)

    objective.SetMaximization()

    # Run the solver
    status = solver.Solve()
    histogram = {x: 0 for x in range(1, 5)}
    if status in [pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE]:
        assignments = {}
        for app, entry in entries.items():
            for is_assigned, weight, hotel_room in entry["constraints"]:
                if is_assigned.solution_value() > 0.5:
                    assert not app in assignments
                    for member in entry["members"]:
                        assignments[member.id] = hotel_room["id"]
                    histogram[len(entry["members"])] += 1
        for group_size, room_count in histogram.items():
            print(f"  {group_size}: {room_count}")
        return assignments
    else:
        log.error(f"Error solving room lottery: {status}")
        return None

@all_renderable()
class Root:
    def index(self, session, message='', page='0', search_text='', order='status', **params):
        if c.DEV_BOX and not int(page):
            page = 1

        total_count = session.query(LotteryApplication.id).count()
        complete_valid_entries = session.query(LotteryApplication.id).filter(LotteryApplication.status == c.COMPLETE).join(
            LotteryApplication.attendee).filter(Attendee.hotel_lottery_eligible == True)
        room_count_base = complete_valid_entries.filter(LotteryApplication.entry_type != c.GROUP_ENTRY)
        count = 0
        search_text = search_text.strip()
        advanced_filters = {}

        if search_text:
            search_results, message = _search(session, search_text)
            if search_results and search_results.count():
                applications = search_results
                count = applications.count()
                if count == total_count:
                    message = 'Every lottery application matched this search.'
            elif not message:
                message = 'No matches found. Try searching the lottery tracking history instead.'

        filter_status = params.get('filter_status', '')
        filter_entry_type = params.get('filter_entry_type', '')
        filter_hotel = params.get('filter_hotel', '')
        filter_inventory = params.get('filter_inventory', '')
        filter_partition = params.get('filter_partition', '')
        filter_export_locked = params.get('filter_export_locked', '')
        filter_staff = params.get('filter_staff', '')

        has_advanced = any([filter_status, filter_entry_type, filter_hotel,
                           filter_inventory, filter_partition, filter_export_locked, filter_staff])

        if has_advanced:
            if not count:
                applications = session.query(LotteryApplication)
            if filter_status:
                applications = applications.filter(LotteryApplication.status == int(filter_status))
            if filter_entry_type:
                applications = applications.filter(LotteryApplication.entry_type == int(filter_entry_type))
            if filter_hotel:
                inv_ids = [str(inv.id) for inv in
                           session.query(HotelRoomInventory).filter_by(hotel_id=filter_hotel).all()]
                if inv_ids:
                    applications = applications.filter(LotteryApplication.assigned_inventory_id.in_(inv_ids))
                else:
                    applications = applications.filter(sa.false())
            if filter_inventory:
                applications = applications.filter(LotteryApplication.assigned_inventory_id == filter_inventory)
            if filter_partition:
                applications = applications.filter(LotteryApplication.partition_id == filter_partition)
            if filter_export_locked == 'true':
                applications = applications.filter(LotteryApplication.export_locked == True)
            elif filter_export_locked == 'false':
                applications = applications.filter(LotteryApplication.export_locked == False)
            if filter_staff == 'true':
                applications = applications.filter(LotteryApplication.is_staff_entry == True)
            elif filter_staff == 'false':
                applications = applications.filter(LotteryApplication.is_staff_entry == False)
            count = applications.count()
            advanced_filters = {k: v for k, v in params.items() if k.startswith('filter_') and v}

        if not count:
            applications = session.query(LotteryApplication)
            count = applications.count()

        applications = applications.order(order).options(joinedload(LotteryApplication.attendee))

        page = int(page)
        if search_text:
            page = page or 1

        pages = range(1, int(math.ceil(count / 100)) + 1)
        applications = applications[-100 + 100*page: 100*page] if page else []

        return {
            'message':        message if isinstance(message, str) else message[-1],
            'page':           page,
            'pages':          pages,
            'search_text':    search_text,
            'search_results': bool(search_text) or has_advanced,
            'applications':   applications,
            'order':          Order(order),
            'search_count':   count,
            'total_count':    total_count,
            'complete_count': complete_valid_entries.count(),
            'suite_count': room_count_base.filter(LotteryApplication.entry_type == c.SUITE_ENTRY).count(),
            'room_count': room_count_base.filter(or_(LotteryApplication.entry_type == c.ROOM_ENTRY,
                                                     LotteryApplication.room_opt_out == False)).count(),
            'advanced_filters': advanced_filters,
            'hotels': session.query(LotteryHotel).filter_by(active=True).order_by(LotteryHotel.name).all(),
            'inventory_blocks': session.query(HotelRoomInventory).filter_by(active=True).all(),
            'partitions': session.query(InventoryPartition).filter_by(active=True).order_by(InventoryPartition.name).all(),
        }  # noqa: E711

    def feed(self, session, message='', page='1', who='', what='', action=''):
        feed = session.query(Tracking).filter(Tracking.model == 'LotteryApplication').order_by(Tracking.when.desc())
        what = what.strip()
        if who:
            feed = feed.filter_by(who=who)
        if what:
            like = '%' + what + '%'
            or_filters = [Tracking.page.ilike(like),
                          Tracking.which.ilike(like),
                          Tracking.data.ilike(like)]
            feed = feed.filter(or_(*or_filters))
        if action:
            feed = feed.filter_by(action=action)
        return {
            'message': message,
            'who': who,
            'what': what,
            'page': page,
            'action': action,
            'count': feed.count(),
            'feed': get_page(page, feed),
            'action_opts': c.TRACKING_OPTS,
            'who_opts': [
                who for [who] in session.query(Tracking).filter(
                    Tracking.model == 'LotteryApplication').distinct().order_by(Tracking.who).values(Tracking.who)]
        }
    
    @ajax
    def validate_hotel_lottery(self, session, id=None, form_list=[], **params):
        application = session.lottery_application(id)

        if not form_list:
            form_list = ["LotteryAdminInfo"]
        elif isinstance(form_list, str):
            form_list = [form_list]
        forms = load_forms(params, application, form_list)
        all_errors = validate_model(session, forms, application, is_admin=True)
        if all_errors:
            return {"error": all_errors}

        return {"success": True}

    @log_pageview
    def form(self, session, message='', return_to='', **params):
        id = params.get('id', None)

        if id in [None, '', 'None']:
            application = LotteryApplication()
        else:
            application = session.lottery_application(id)

        forms = load_forms(params, application, ['LotteryAdminInfo'])

        if cherrypy.request.method == 'POST':
            for form in forms.values():
                form.populate_obj(application, is_admin=True)
            application.hotel_confirmation_number = params.get('hotel_confirmation_number', '') or None

            message = '{}\'s entry (conf # {}) has been saved.'.format(application.attendee_name,
                                                                       application.confirmation_num)
            stay_on_form = params.get('save_return_to_search', False) is False
            session.add(application)
            if application.orig_value_of('status') != application.status and application.status in [
                    c.REJECTED, c.CANCELLED, c.REMOVED, c.WITHDRAWN]:
                application.attendee.hotel_eligible = True
                session.add(application.attendee)
            session.commit()
            if stay_on_form:
                    raise HTTPRedirect('form?id={}&message={}&return_to={}', application.id, message, return_to)
            else:
                if return_to:
                    raise HTTPRedirect(return_to + '&message={}', 'Application updated.')
                else:
                    raise HTTPRedirect('index?message={}', message)

        return {
            'message':    message,
            'application':   application,
            'forms': forms,
            'return_to':  return_to,
        }

    def history(self, session, id):
        application = session.lottery_application(id)
        return {
            'application':  application,
            'emails': session.query(Email).filter(Email.model == 'LotteryApplication',
                                                  Email.fk_id == id
                                                  ).order_by(Email.when).all(),
            'changes': session.query(Tracking).filter(Tracking.model == 'LotteryApplication', Tracking.fk_id == id
                                                      ).order_by(Tracking.when).all(),
            'pageviews': session.query(PageViewTracking).filter(PageViewTracking.which == repr(application)
                                                                ).order_by(PageViewTracking.when).all(),
        }
    
    def lottery_runs(self, session, message=''):
        runs = session.query(LotteryRun).order_by(LotteryRun.run_at.desc()).all()
        hotels = session.query(LotteryHotel).filter_by(active=True).order_by(LotteryHotel.name).all()
        room_types = session.query(LotteryRoomType).filter_by(active=True, is_suite=False).order_by(LotteryRoomType.name).all()
        suite_types = session.query(LotteryRoomType).filter_by(active=True, is_suite=True).order_by(LotteryRoomType.name).all()
        inventory_blocks = session.query(HotelRoomInventory).filter_by(active=True).order_by(
            HotelRoomInventory.hotel_id, HotelRoomInventory.name).all()
        partitions = session.query(InventoryPartition).filter_by(active=True).order_by(InventoryPartition.name).all()
        return {
            'runs': runs,
            'hotels': hotels,
            'room_types': room_types,
            'suite_types': suite_types,
            'inventory_blocks': inventory_blocks,
            'partitions': partitions,
            'message': message,
        }

    def lottery_run_detail(self, session, id, message=''):
        lottery_run = session.query(LotteryRun).get(id)
        applications = session.query(LotteryApplication).filter(
            LotteryApplication.lottery_run_id == id,
            LotteryApplication.entry_type != c.GROUP_ENTRY,
        ).order_by(LotteryApplication.assigned_inventory_id).all()
        partitions = session.query(InventoryPartition).filter_by(active=True).order_by(InventoryPartition.name).all()
        partition_lookup = {str(p.id): p.name for p in partitions}
        return {
            'lottery_run': lottery_run,
            'applications': applications,
            'hotels': session.query(LotteryHotel).filter_by(active=True).order_by(LotteryHotel.name).all(),
            'room_types': session.query(LotteryRoomType).filter_by(is_suite=False, active=True).order_by(LotteryRoomType.name).all(),
            'suite_types': session.query(LotteryRoomType).filter_by(is_suite=True, active=True).order_by(LotteryRoomType.name).all(),
            'partition_lookup': partition_lookup,
            'message': message,
        }

    def update_lottery_run(self, session, id, name, **params):
        lottery_run = session.query(LotteryRun).get(id)
        lottery_run.name = name
        session.commit()
        raise HTTPRedirect('lottery_run_detail?id={}&message={}', id, 'Run name updated.')

    def award_run(self, session, id, **params):
        lottery_run = session.query(LotteryRun).get(id)
        if lottery_run.status != c.LOTTERY_PENDING:
            raise HTTPRedirect('lottery_run_detail?id={}&message={}', id, 'This run cannot be awarded.')

        applications = session.query(LotteryApplication).join(LotteryApplication.attendee).filter(
            LotteryApplication.lottery_run_id == id,
            LotteryApplication.status == c.PROCESSED,
            Attendee.hotel_lottery_eligible == True,
        ).all()

        for app in applications:
            app.status = c.AWARDED
            if c.HOTEL_LOTTERY_GUARANTEE_HOURS:
                dt = (localized_now() + timedelta(hours=c.HOTEL_LOTTERY_GUARANTEE_HOURS)).strftime('%Y-%m-%d')
                app.deposit_cutoff_date = datetime.strptime(dt + ' 23:59', '%Y-%m-%d %H:%M').date()
            session.add(app)

        lottery_run.status = c.LOTTERY_AWARDED
        lottery_run.awarded_at = datetime.now(UTC)
        session.commit()
        raise HTTPRedirect('lottery_run_detail?id={}&message={}', id,
                           f"{len(applications)} entries awarded.")

    def revert_run(self, session, id, **params):
        lottery_run = session.query(LotteryRun).get(id)
        if lottery_run.status != c.LOTTERY_PENDING:
            raise HTTPRedirect('lottery_run_detail?id={}&message={}', id, 'This run cannot be reverted.')

        applications = session.query(LotteryApplication).filter(
            LotteryApplication.lottery_run_id == id,
            LotteryApplication.status == c.PROCESSED,
        ).all()

        for app in applications:
            app.status = c.COMPLETE
            app.assigned_inventory_id = None
            app.partition_id = None
            app.lottery_name = ''
            app.lottery_run_id = None
            session.add(app)

        lottery_run.status = c.LOTTERY_REVERTED
        lottery_run.reverted_at = datetime.now(UTC)
        session.commit()
        raise HTTPRedirect('lottery_runs?message={}',
                           f"Run '{lottery_run.name}' reverted. {len(applications)} entries reset to complete.")

    def delete_run(self, session, id, **params):
        lottery_run = session.query(LotteryRun).get(id)
        if lottery_run.status != c.LOTTERY_REVERTED:
            raise HTTPRedirect('lottery_run_detail?id={}&message={}', id, 'Only reverted runs can be deleted.')

        name = lottery_run.name
        session.delete(lottery_run)
        session.commit()
        raise HTTPRedirect('lottery_runs?message={}', f"Run '{name}' has been deleted.")

    def manage_inventory(self, session, message=''):
        inventory = session.query(HotelRoomInventory).order_by(
            HotelRoomInventory.hotel_id, HotelRoomInventory.is_suite, HotelRoomInventory.name).all()

        # Count assigned per block
        assigned_counts = session.query(
            LotteryApplication.assigned_inventory_id, func.count(LotteryApplication.id)
        ).filter(
            LotteryApplication.status.in_(c.HOTEL_LOTTERY_AWARD_STATUSES),
            LotteryApplication.entry_type != c.GROUP_ENTRY,
            LotteryApplication.assigned_inventory_id != None,
        ).group_by(LotteryApplication.assigned_inventory_id).all()
        assigned_per_block = defaultdict(int, {str(inv_id): cnt for inv_id, cnt in assigned_counts})

        return {
            'inventory': inventory,
            'assigned_per_block': assigned_per_block,
            'hotels': session.query(LotteryHotel).filter_by(active=True).order_by(LotteryHotel.name).all(),
            'room_types': session.query(LotteryRoomType).filter_by(is_suite=False, active=True).order_by(LotteryRoomType.name).all(),
            'suite_types': session.query(LotteryRoomType).filter_by(is_suite=True, active=True).order_by(LotteryRoomType.name).all(),
            'message': message,
        }

    def edit_inventory_item(self, session, id=None, message='', **params):
        if id and id != 'None' and id != '':
            item = session.query(HotelRoomInventory).get(id)
        else:
            item = None

        if not item:
            item = HotelRoomInventory()

        # Build hotel night dates for per-night quantity grid
        event_nights = []
        day = c.HOTEL_LOTTERY_CHECKIN_START.date()
        end = c.HOTEL_LOTTERY_CHECKOUT_END.date()
        while day < end:
            event_nights.append(day)
            day += timedelta(days=1)

        if cherrypy.request.method == 'POST':
            item.hotel_id = params['hotel']
            item.is_suite = params.get('is_suite') == 'true'
            if item.is_suite:
                item.suite_type_id = params.get('suite_type') or None
                item.room_type_id = None
            else:
                item.room_type_id = params.get('room_type') or None
                item.suite_type_id = None
            try:
                item.quantity = int(params.get('quantity', 0))
                item.capacity = int(params.get('capacity', 2))
                item.min_capacity = int(params.get('min_capacity', 1))
            except (ValueError, TypeError):
                raise HTTPRedirect('edit_inventory_item?id={}&message={}', item.id if item.id else '',
                                   'Quantity, capacity, and min capacity must be numbers.')
            item.name = params.get('name', '')
            item.active = params.get('active') == 'true'
            item.vault_reference = params.get('vault_reference', '') or None
            item.info_url = params.get('info_url', '').strip()
            item.price = params.get('price', '').strip()
            item.staff_price = params.get('staff_price', '').strip()
            session.add(item)
            session.flush()

            # Save per-night quantities
            existing_nq = {nq.night_date: nq for nq in item.night_quantities}
            for night in event_nights:
                qty_str = params.get(f'night_qty_{night.isoformat()}', '')
                if qty_str != '':
                    try:
                        qty = int(qty_str)
                    except (ValueError, TypeError):
                        continue
                    if night in existing_nq:
                        existing_nq[night].quantity = qty
                    else:
                        nq = InventoryNightQuantity(inventory_id=item.id, night_date=night, quantity=qty)
                        session.add(nq)

            session.commit()

            # Auto-process waitlist for this inventory block
            waitlist_result = _fulfill_waitlist(session, inventory_id=str(item.id))
            save_msg = 'Inventory item saved.'
            if waitlist_result['fulfilled'] > 0:
                save_msg += f" Waitlist: {waitlist_result['fulfilled']} entries fulfilled."

            raise HTTPRedirect('manage_inventory?message={}', save_msg)

        return {
            'item': item,
            'hotels': session.query(LotteryHotel).filter_by(active=True).all(),
            'room_types': session.query(LotteryRoomType).filter_by(is_suite=False, active=True).all(),
            'suite_types': session.query(LotteryRoomType).filter_by(is_suite=True, active=True).all(),
            'event_nights': event_nights,
            'message': message,
        }

    def settings(self, session, message=''):
        return {
            'message': message,
        }

    @ajax
    def vault_usage(self, session, month=''):
        if not c.VAULT_ENABLED:
            return {'error': 'Vault integration is not enabled.'}

        from uber.vault import get_usage, get_billing

        try:
            usage = get_usage(month=month if month else None)
            billing = get_billing()
            return {'success': True, 'usage': usage, 'billing': billing}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def setup_vault_form(self, session, **params):
        if not c.VAULT_ENABLED:
            raise HTTPRedirect('settings?message={}', 'Vault integration is not enabled.')

        from uber.vault import setup_capture_form

        form_id = c.VAULT_CAPTURE_FORM_ID or 'hotel-card-capture'

        # Embedded JS reports iframe height to parent via ResizeObserver.
        # No card data is touched — card metadata comes via webhook.
        embedded_js = """
        document.addEventListener('DOMContentLoaded', function() {
            function postHeight() {
                var height = document.documentElement.scrollHeight;
                window.parent.postMessage({ height: height }, '*');
            }
            if (typeof ResizeObserver !== 'undefined') {
                new ResizeObserver(postHeight).observe(document.body);
            } else {
                setInterval(postHeight, 500);
            }
            postHeight();
        });
        """

        # Success callback sends token to parent window via postMessage
        success_callback_js = """
        function(data) {
            window.parent.postMessage({ token: data.token }, '*');
        }
        """

        import base64 as b64
        encoded_js = b64.b64encode(embedded_js.strip().encode()).decode()

        try:
            result = setup_capture_form(
                form_id=form_id,
                success_callback_js=success_callback_js,
                embedded_js=encoded_js,
            )
        except Exception as e:
            raise HTTPRedirect('settings?message={}',
                               f"Error setting up vault form: {e}")

        raise HTTPRedirect('settings?message={}',
                           f"Vault capture form created/updated: {result.get('id', form_id)}")

    def manage_hotels(self, session, message=''):
        hotels = session.query(LotteryHotel).order_by(LotteryHotel.name).all()
        return {
            'hotels': hotels,
            'message': message,
        }

    def edit_hotel(self, session, id=None, message='', **params):
        if id and id not in ('None', ''):
            hotel = session.query(LotteryHotel).get(id)
        else:
            hotel = None

        if not hotel:
            hotel = LotteryHotel()

        if cherrypy.request.method == 'POST':
            hotel.name = params.get('name', '').strip()
            hotel.export_name = params.get('export_name', '').strip()
            hotel.description = params.get('description', '').strip()
            hotel.description_right = params.get('description_right', '').strip()
            hotel.footnote = params.get('footnote', '').strip()
            hotel.active = params.get('active') == 'true'
            session.add(hotel)
            session.commit()
            raise HTTPRedirect('manage_hotels?message={}', f"Hotel '{hotel.name}' saved.")

        return {
            'hotel': hotel,
            'message': message,
        }

    def manage_room_types(self, session, message=''):
        room_types = session.query(LotteryRoomType).order_by(
            LotteryRoomType.is_suite, LotteryRoomType.name).all()
        return {
            'room_types': room_types,
            'message': message,
        }

    def edit_room_type(self, session, id=None, message='', **params):
        if id and id not in ('None', ''):
            room_type = session.query(LotteryRoomType).get(id)
        else:
            room_type = None

        if not room_type:
            room_type = LotteryRoomType()

        if cherrypy.request.method == 'POST':
            room_type.name = params.get('name', '').strip()
            room_type.export_name = params.get('export_name', '').strip()
            room_type.description = params.get('description', '').strip()
            room_type.description_right = params.get('description_right', '').strip()
            room_type.footnote = params.get('footnote', '').strip()
            room_type.capacity = int(params.get('capacity', 4))
            room_type.min_capacity = int(params.get('min_capacity', 1))
            room_type.is_suite = params.get('is_suite') == 'true'
            room_type.active = params.get('active') == 'true'
            session.add(room_type)
            session.commit()
            raise HTTPRedirect('manage_room_types?message={}', f"Room type '{room_type.name}' saved.")

        return {
            'room_type': room_type,
            'message': message,
        }

    def export_tracking(self, session, message=''):
        hotels = []
        for hotel in session.query(LotteryHotel).filter_by(active=True).all():
            last_export = session.query(HotelExportLog).filter(
                HotelExportLog.hotel_id == hotel.id, HotelExportLog.export_type == 'room_export'
            ).order_by(HotelExportLog.exported_at.desc()).first()

            last_import = session.query(HotelExportLog).filter(
                HotelExportLog.hotel_id == hotel.id, HotelExportLog.export_type == 'confirmation_import'
            ).order_by(HotelExportLog.exported_at.desc()).first()

            hotel_inventory_ids = [str(inv.id) for inv in
                                    session.query(HotelRoomInventory).filter_by(hotel_id=hotel.id).all()]
            bookings = session.query(LotteryApplication).filter(
                LotteryApplication.assigned_inventory_id.in_(hotel_inventory_ids),
                LotteryApplication.status.in_([c.AWARDED, c.SECURED]),
                LotteryApplication.entry_type != c.GROUP_ENTRY,
            )

            total_bookings = bookings.count()
            missing_confirmation = bookings.filter(
                or_(LotteryApplication.hotel_confirmation_number == None,
                    LotteryApplication.hotel_confirmation_number == '')
            ).count()

            dirty_count = 0
            if last_export:
                dirty_count = bookings.filter(
                    LotteryApplication.last_modified_at > last_export.exported_at
                ).count()

            hotels.append({
                'hotel': hotel,
                'last_export': last_export,
                'last_import': last_import,
                'total_bookings': total_bookings,
                'missing_confirmation': missing_confirmation,
                'dirty_count': dirty_count,
            })

        return {
            'hotels': hotels,
            'message': message,
        }
        
    def run_lottery(self, session, lottery_group="attendee", lottery_type="room", run_name="", **params):
        if lottery_type == "room":
            lottery_type_val = c.ROOM_ENTRY
        elif lottery_type == "suite":
            lottery_type_val = c.SUITE_ENTRY
        else:
            return {'error': f'Invalid lottery type: {lottery_type}'}
        applications = session.query(LotteryApplication).join(LotteryApplication.attendee
                                                              ).filter(LotteryApplication.status == c.COMPLETE,
                                                                       Attendee.hotel_lottery_eligible == True)

        cutoff = None
        if params.get('cutoff', ''):
            cutoff = dateparser.parse(params['cutoff']).replace(tzinfo=c.EVENT_TIMEZONE)
            applications = applications.filter(LotteryApplication.last_submitted < cutoff)

        # We always grab all roommate entries, but the solver only looks at those that have a matching parent
        # in the lottery batch.
        if lottery_type_val == c.SUITE_ENTRY:
            applications = applications.filter(LotteryApplication.entry_type.in_([lottery_type_val, c.GROUP_ENTRY]))
        else:
            applications = applications.filter(or_(LotteryApplication.entry_type.in_([lottery_type_val, c.GROUP_ENTRY]),
                                                   LotteryApplication.room_opt_out == False))

        # If lottery_group is "both" don't filter either way
        if lottery_group == "staff":
            applications = applications.filter(LotteryApplication.is_staff_entry == True)
        elif lottery_group == "attendee":
            applications = applications.filter(LotteryApplication.is_staff_entry == False)

        applications = applications.all()

        # Count already-assigned applications per inventory block per night
        already_assigned_query = session.query(LotteryApplication).join(LotteryApplication.attendee).filter(
            LotteryApplication.status.in_(c.HOTEL_LOTTERY_AWARD_STATUSES),
            LotteryApplication.entry_type != c.GROUP_ENTRY,
            LotteryApplication.assigned_inventory_id != None,
        )

        # Partition filter: only count same-partition assignments toward capacity
        partition_filter = params.get('partition_filter', '')
        inventory_filter = params.get('inventory_filter', '')

        if partition_filter:
            # Partitioned run: only count same-partition assignments
            already_assigned = already_assigned_query.filter(
                LotteryApplication.partition_id == partition_filter).all()
        else:
            # Non-partitioned run: only count non-partitioned assignments
            already_assigned = already_assigned_query.filter(
                LotteryApplication.partition_id == None).all()

        # Build {inventory_id: {night_date_iso: count}} for already-assigned
        assigned_per_block_night = defaultdict(lambda: defaultdict(int))
        for app in already_assigned:
            if app.assigned_check_in_date and app.assigned_check_out_date:
                day = app.assigned_check_in_date
                while day < app.assigned_check_out_date:
                    assigned_per_block_night[str(app.assigned_inventory_id)][day.isoformat()] += 1
                    day += timedelta(days=1)

        is_suite = lottery_type_val == c.SUITE_ENTRY
        inventory_table = HotelRoomInventory.get_inventory(session, is_suite=is_suite)

        # Apply filters
        hotel_filter = params.get('hotel_filter', '')
        room_type_filter = params.get('room_type_filter', '')
        if hotel_filter:
            hotel_filter_set = set(hotel_filter.split(','))
            inventory_table = [r for r in inventory_table if r['hotel_id'] in hotel_filter_set]
        if room_type_filter:
            room_type_filter_set = set(room_type_filter.split(','))
            inventory_table = [r for r in inventory_table if r['room_type'] in room_type_filter_set]
        if inventory_filter:
            inventory_filter_set = set(inventory_filter.split(','))
            inventory_table = [r for r in inventory_table if r['id'] in inventory_filter_set]

        # Build partition allocation maps
        partition_qty_map = {}  # {block_id: cap} for the selected partition
        total_partitioned_map = {}  # {block_id: total across all partitions}
        if partition_filter:
            for pb in session.query(InventoryPartitionBlock).filter_by(partition_id=partition_filter).all():
                partition_qty_map[str(pb.inventory_id)] = pb.quantity
        else:
            # For non-partitioned runs, compute total partitioned allocation per block
            for pb in session.query(InventoryPartitionBlock).all():
                bid = str(pb.inventory_id)
                total_partitioned_map[bid] = total_partitioned_map.get(bid, 0) + pb.quantity

        available_rooms = deepcopy(inventory_table)
        for block in available_rooms:
            block_id = block['id']

            if partition_filter:
                # Partitioned run: cap at partition allocation
                partition_cap = partition_qty_map.get(block_id, 0)
                if partition_cap <= 0:
                    block['quantity'] = 0
                    if block.get('night_quantities'):
                        block['night_quantities'] = {k: 0 for k in block['night_quantities']}
                    continue
                block['quantity'] = min(block['quantity'], partition_cap)
                if block.get('night_quantities'):
                    block['night_quantities'] = {k: min(v, partition_cap) for k, v in block['night_quantities'].items()}
            else:
                # Non-partitioned run: subtract total partition allocations from capacity
                reserved = total_partitioned_map.get(block_id, 0)
                if reserved:
                    block['quantity'] = max(0, block['quantity'] - reserved)
                    if block.get('night_quantities'):
                        block['night_quantities'] = {k: max(0, v - reserved) for k, v in block['night_quantities'].items()}

            if block.get('night_quantities'):
                for night_iso, qty in block['night_quantities'].items():
                    already = assigned_per_block_night.get(block_id, {}).get(night_iso, 0)
                    block['night_quantities'][night_iso] = max(0, qty - already)
            else:
                total_assigned = sum(assigned_per_block_night.get(block_id, {}).values())
                if total_assigned:
                    block['quantity'] = max(0, block['quantity'] - total_assigned)

        rooms_available_before = sum([x['quantity'] for x in available_rooms])
        assignments = solve_lottery(applications, available_rooms, lottery_type=lottery_type_val)

        # Create LotteryRun record
        lottery_run = LotteryRun(
            name=run_name or f"{lottery_group}_{lottery_type}_{localized_now().strftime('%Y%m%d_%H%M%S')}",
            lottery_group=lottery_group,
            lottery_type=lottery_type,
            cutoff=cutoff,
            hotel_filter=hotel_filter or None,
            room_type_filter=room_type_filter or None,
            inventory_filter=inventory_filter or None,
            partition_filter=partition_filter or None,
            entries_considered=len([x for x in applications if x.entry_type != c.GROUP_ENTRY]),
            rooms_available_before=rooms_available_before,
        )
        session.add(lottery_run)
        session.flush()

        num_rooms_assigned = 0
        for application in applications:
            if application.id in assignments:
                inventory_id = assignments[application.id]
                application.assigned_inventory_id = inventory_id
                application.lottery_name = lottery_run.name
                application.lottery_run_id = lottery_run.id
                application.assigned_check_in_date = application.earliest_checkin_date
                application.assigned_check_out_date = application.latest_checkout_date
                application.status = c.PROCESSED
                if partition_filter:
                    application.partition_id = partition_filter
                session.add(application)
                if not application.parent_application:
                    num_rooms_assigned += 1

        lottery_run.rooms_assigned = num_rooms_assigned
        session.commit()

        raise HTTPRedirect('lottery_run_detail?id={}&message={}', lottery_run.id,
                           f"Lottery run complete: {num_rooms_assigned} rooms assigned.")
    
    def hotel_inventory(self, session, message='', partition='all'):
        # Build event night dates
        event_nights = []
        day = c.HOTEL_LOTTERY_CHECKIN_START.date()
        end = c.HOTEL_LOTTERY_CHECKOUT_END.date()
        while day < end:
            event_nights.append(day)
            day += timedelta(days=1)

        partitions = session.query(InventoryPartition).filter_by(active=True).order_by(InventoryPartition.name).all()

        # Determine partition filter for assigned/waitlist counting
        # partition='all' -> count all apps, show full capacity
        # partition='default' -> count only non-partitioned apps, show capacity minus partition allocations
        # partition=<uuid> -> count only that partition's apps, show partition allocation as capacity
        filter_partition_id = None
        filtering_default = False
        if partition == 'default':
            filtering_default = True
        elif partition not in ('all', ''):
            filter_partition_id = partition

        # Get assigned non-group applications, optionally filtered by partition
        app_query = session.query(LotteryApplication).filter(
            LotteryApplication.status.in_(c.HOTEL_LOTTERY_AWARD_STATUSES),
            LotteryApplication.entry_type != c.GROUP_ENTRY,
            LotteryApplication.assigned_inventory_id != None,
        )
        if filter_partition_id:
            app_query = app_query.filter(LotteryApplication.partition_id == filter_partition_id)
        elif filtering_default:
            app_query = app_query.filter(LotteryApplication.partition_id == None)
        assigned_apps = app_query.all()

        # Build per-block per-night assignment counts and status counts
        assigned_per_block_night = defaultdict(lambda: defaultdict(int))
        status_per_block = defaultdict(lambda: defaultdict(int))
        for app in assigned_apps:
            block_id = str(app.assigned_inventory_id)
            status_per_block[block_id][app.status] += 1
            if app.assigned_check_in_date and app.assigned_check_out_date:
                d = app.assigned_check_in_date
                while d < app.assigned_check_out_date:
                    assigned_per_block_night[block_id][d] += 1
                    d += timedelta(days=1)

        # Build per-block per-night waitlist demand
        waitlist_per_block_night = defaultdict(lambda: defaultdict(int))
        for app in assigned_apps:
            if app.status != c.SECURED:
                continue
            block_id = str(app.assigned_inventory_id)
            if app.earliest_checkin_date and app.assigned_check_in_date:
                d = app.earliest_checkin_date
                while d < app.assigned_check_in_date:
                    waitlist_per_block_night[block_id][d] += 1
                    d += timedelta(days=1)
            if app.latest_checkout_date and app.assigned_check_out_date:
                d = app.assigned_check_out_date
                while d < app.latest_checkout_date:
                    waitlist_per_block_night[block_id][d] += 1
                    d += timedelta(days=1)

        # Build partition allocation maps for capacity adjustments
        partition_alloc_per_block = {}  # {block_id: allocation} for the selected partition
        total_partitioned_per_block = defaultdict(int)  # {block_id: sum of all partition allocations}
        if filter_partition_id:
            for pb in session.query(InventoryPartitionBlock).filter_by(partition_id=filter_partition_id).all():
                partition_alloc_per_block[str(pb.inventory_id)] = pb.quantity
        for pb in session.query(InventoryPartitionBlock).all():
            total_partitioned_per_block[str(pb.inventory_id)] += pb.quantity

        hotel_lookup = {str(h.id): h for h in session.query(LotteryHotel).all()}

        def effective_capacity(block_id, block_qty):
            if filter_partition_id:
                return min(partition_alloc_per_block.get(block_id, 0), block_qty)
            elif filtering_default:
                return max(0, block_qty - total_partitioned_per_block.get(block_id, 0))
            else:
                return block_qty

        def build_inventory_data(is_suite):
            inventory = defaultdict(list)
            for inv in session.query(HotelRoomInventory).filter_by(is_suite=is_suite, active=True).all():
                hotel_obj = hotel_lookup.get(str(inv.hotel_id))
                block_id = str(inv.id)
                nq_map = inv.night_quantity_map

                night_data = []
                for night in event_nights:
                    raw_qty = nq_map.get(night, inv.quantity) if nq_map else inv.quantity
                    available = effective_capacity(block_id, raw_qty)
                    assigned = assigned_per_block_night.get(block_id, {}).get(night, 0)
                    waitlisted = waitlist_per_block_night.get(block_id, {}).get(night, 0)
                    night_data.append({
                        'night': night,
                        'available': available,
                        'assigned': assigned,
                        'remaining': max(0, available - assigned),
                        'waitlisted': waitlisted,
                    })

                total_assigned = sum(status_per_block.get(block_id, {}).values())
                info = {
                    'inventory': inv,
                    'room_type': inv.suite_type if is_suite else inv.room_type,
                    'quantity': effective_capacity(block_id, inv.quantity),
                    'nights': night_data,
                    'total_assigned': total_assigned,
                    c.PROCESSED: status_per_block.get(block_id, {}).get(c.PROCESSED, 0),
                    c.AWARDED: status_per_block.get(block_id, {}).get(c.AWARDED, 0),
                    c.SECURED: status_per_block.get(block_id, {}).get(c.SECURED, 0),
                }
                inventory[hotel_obj].append(info)
            return inventory

        # Build chart data: per-night totals by hotel
        chart_data = {}
        for inv in session.query(HotelRoomInventory).filter_by(active=True).all():
            hotel_name = hotel_lookup.get(str(inv.hotel_id), None)
            hotel_name = hotel_name.name if hotel_name else 'Unknown'
            if hotel_name not in chart_data:
                chart_data[hotel_name] = {
                    'available': [0] * len(event_nights),
                    'assigned': [0] * len(event_nights),
                    'waitlisted': [0] * len(event_nights),
                }
            nq_map = inv.night_quantity_map
            block_id = str(inv.id)
            for i, night in enumerate(event_nights):
                raw_qty = nq_map.get(night, inv.quantity) if nq_map else inv.quantity
                chart_data[hotel_name]['available'][i] += effective_capacity(block_id, raw_qty)
                chart_data[hotel_name]['assigned'][i] += assigned_per_block_night.get(block_id, {}).get(night, 0)
                chart_data[hotel_name]['waitlisted'][i] += waitlist_per_block_night.get(block_id, {}).get(night, 0)

        # Build combined total across all hotels
        total = {'available': [0] * len(event_nights), 'assigned': [0] * len(event_nights), 'waitlisted': [0] * len(event_nights)}
        for data in chart_data.values():
            for i in range(len(event_nights)):
                total['available'][i] += data['available'][i]
                total['assigned'][i] += data['assigned'][i]
                total['waitlisted'][i] += data['waitlisted'][i]
        chart_data['_total'] = total

        return {
            'room_inventory': build_inventory_data(is_suite=False),
            'suite_inventory': build_inventory_data(is_suite=True),
            'event_nights': event_nights,
            'partitions': partitions,
            'chart_data': chart_data,
            'now': localized_now(),
            'current_partition': partition,
        }

    @ajax
    def inventory_assignees(self, session, inventory_id, night_date='', partition='all'):
        query = session.query(LotteryApplication).filter(
            LotteryApplication.assigned_inventory_id == inventory_id,
            LotteryApplication.status.in_(c.HOTEL_LOTTERY_AWARD_STATUSES),
            LotteryApplication.entry_type != c.GROUP_ENTRY,
        )
        if night_date:
            nd = date.fromisoformat(night_date)
            query = query.filter(
                LotteryApplication.assigned_check_in_date <= nd,
                LotteryApplication.assigned_check_out_date > nd,
            )
        if partition == 'default':
            query = query.filter(LotteryApplication.partition_id == None)
        elif partition not in ('all', ''):
            query = query.filter(LotteryApplication.partition_id == partition)

        apps = query.order_by(LotteryApplication.assigned_check_in_date).all()
        assignees = []
        for app in apps:
            assignees.append({
                'app_id': app.id,
                'attendee_id': str(app.attendee.id) if app.attendee else '',
                'name': app.attendee_name,
                'conf_num': app.confirmation_num or '',
                'status': app.status_label,
                'check_in': app.assigned_check_in_date.strftime('%a %-m/%-d') if app.assigned_check_in_date else '',
                'check_out': app.assigned_check_out_date.strftime('%a %-m/%-d') if app.assigned_check_out_date else '',
                'partition': app.partition.name if app.partition_id and app.partition else '',
            })
        return {'assignees': assignees}

    @csv_file
    def assigned_entries(self, out, session, lock_entries=''):
        out.writerow(['Lottery Name', 'Staff Entry?',
                      'CheckInDate', 'CheckOutDate', 'NumberofGuests', 'HotelName', 'RoomType', 'SpecialRequest', 'AccessibleRoom',
                      'RewardsNumber',
                      'Guest1CheckInDate', 'Guest1CheckOutDate', 'Guest1FirstName', 'Guest1LastName', 'Guest1Phone', 'Guest1Email',
                      'Guest2CheckInDate', 'Guest2CheckOutDate', 'Guest2FirstName', 'Guest2LastName', 'Guest2Phone', 'Guest2Email',
                      'Guest3CheckInDate', 'Guest3CheckOutDate', 'Guest3FirstName', 'Guest3LastName', 'Guest3Phone', 'Guest3Email',
                      'Guest4CheckInDate', 'Guest4CheckOutDate', 'Guest4FirstName', 'Guest4LastName', 'Guest4Phone', 'Guest4Email',])

        assigned_entries = session.query(LotteryApplication).filter(
            or_(LotteryApplication.status == c.AWARDED, LotteryApplication.status == c.SECURED),
            LotteryApplication.entry_type != c.GROUP_ENTRY).order_by(LotteryApplication.assigned_inventory_id)

        # Only lock exported entries when explicitly requested
        if lock_entries:
            for entry in assigned_entries:
                if not entry.export_locked:
                    entry.export_locked = True
                    session.add(entry)
            session.commit()

        for entry in assigned_entries:
            check_in_date = entry.assigned_check_in_date
            check_out_date = entry.assigned_check_out_date
            num_guests = len(entry.valid_group_members) + 1
            hotel_name = entry.assigned_hotel.name if entry.assigned_hotel else ''
            room_type_name = (entry.assigned_suite_type.name if entry.assigned_suite_type
                              else entry.assigned_room_type.name if entry.assigned_room_type else '')
            row = [entry.lottery_name, entry.is_staff_entry, check_in_date, check_out_date, num_guests, hotel_name,
                   room_type_name,
                   entry.ada_requests, entry.wants_ada,
                   entry.hotel_rewards_number,
                   check_in_date, check_out_date, entry.legal_first_name, entry.legal_last_name, entry.cellphone, entry.email]
            for member in entry.valid_group_members:
                row.extend([check_in_date, check_out_date, member.legal_first_name, member.legal_last_name, member.cellphone, member.email])
            out.writerow(row)
    
    @xlsx_file
    def hotel_inventory_xlsx(self, out, session, hotel_id):
        rows = []

        hotel_inventory_ids = [str(inv.id) for inv in
                               session.query(HotelRoomInventory).filter_by(hotel_id=hotel_id).all()]
        assigned_entries = session.query(LotteryApplication).filter(
            LotteryApplication.status.in_(c.HOTEL_LOTTERY_AWARD_STATUSES),
            LotteryApplication.entry_type != c.GROUP_ENTRY,
            LotteryApplication.assigned_inventory_id.in_(hotel_inventory_ids),
            )

        first_entry = assigned_entries.order_by(LotteryApplication.assigned_check_in_date).first()
        if not first_entry:
            return  # No assigned entries for this hotel
        earliest_check_in = first_entry.assigned_check_in_date
        latest_check_out = assigned_entries.order_by(LotteryApplication.assigned_check_out_date.desc()).first().assigned_check_out_date
        date_range = [earliest_check_in + timedelta(days=x) for x in range(0, (latest_check_out - earliest_check_in).days)] + [latest_check_out]

        # Group inventory blocks by room type
        inv_by_room_type = defaultdict(list)
        inv_by_suite_type = defaultdict(list)
        for inv in session.query(HotelRoomInventory).filter(HotelRoomInventory.id.in_(hotel_inventory_ids)).all():
            if inv.is_suite:
                inv_by_suite_type[str(inv.suite_type_id)].append(str(inv.id))
            else:
                inv_by_room_type[str(inv.room_type_id)].append(str(inv.id))

        header_row = [''] + [d.strftime("%A %-m/%-d") for d in date_range]
        for rt in session.query(LotteryRoomType).filter_by(is_suite=False, active=True).order_by(LotteryRoomType.name).all():
            inv_ids = inv_by_room_type.get(str(rt.id), [])
            row = [rt.name]
            for d in date_range:
                row.append(assigned_entries.filter(LotteryApplication.assigned_inventory_id.in_(inv_ids),
                                                   LotteryApplication.assigned_check_in_date <= d,
                                                   LotteryApplication.assigned_check_out_date >= d).count() if inv_ids else 0)
            rows.append(row)

        has_suites = any(inv_by_suite_type.values())
        if has_suites:
            for st in session.query(LotteryRoomType).filter_by(is_suite=True, active=True).order_by(LotteryRoomType.name).all():
                inv_ids = inv_by_suite_type.get(str(st.id), [])
                row = [st.name]
                for d in date_range:
                    row.append(assigned_entries.filter(LotteryApplication.assigned_inventory_id.in_(inv_ids),
                                                    LotteryApplication.assigned_check_in_date <= d,
                                                    LotteryApplication.assigned_check_out_date >= d).count() if inv_ids else 0)
                rows.append(row)

        out.writerows(header_row, rows)

    @multifile_zipfile
    def hotel_inventory_zip(self, zip_file, session):
        for hotel in session.query(LotteryHotel).filter_by(active=True).all():
            hotel_inv_ids = [str(inv.id) for inv in
                             session.query(HotelRoomInventory).filter_by(hotel_id=hotel.id).all()]
            assigned_entries = session.query(LotteryApplication).filter(
                LotteryApplication.status.in_(c.HOTEL_LOTTERY_AWARD_STATUSES),
                LotteryApplication.entry_type != c.GROUP_ENTRY,
                LotteryApplication.assigned_inventory_id.in_(hotel_inv_ids),
                )

            if assigned_entries.count():
                output = self.hotel_inventory_xlsx(hotel_id=hotel.id, set_headers=False)
                zip_file.writestr(f'hotel_inventory_{hotel.name}.xlsx', output)

    @csv_file
    def accepted_dealers(self, out, session):
        out.writerow(['Group Name', 'Group ID', 'Reg ID'])

        for dealer in session.query(Attendee).join(Group, Attendee.group_id == Group.id).filter(
            Group.is_dealer, Group.status.in_(c.DEALER_ACCEPTED_STATUSES)):
            out.writerow([dealer.group.name, dealer.group.id, dealer.id])

    @csv_file
    def interchange_export(self, out, session, staff_lottery=False):
        def print_dt(dt):
            if not dt:
                return ""

            if isinstance(dt, datetime):
                return dt.astimezone(c.EVENT_TIMEZONE).strftime('%m/%d/%Y %H:%M:%S')
            else:
                return dt.strftime('%m/%d/%Y')
        
        def print_bool(bool):
            return "TRUE" if bool else "FALSE"

        country_codes = {}
        for country in list(pycountry.countries):
            value = country.name if "Taiwan" not in country.name else "Taiwan"
            country_codes[value] = f"{country.alpha_2};{country.name}"

        header_row = []
        # Config data and IDs
        header_row.extend(["Lottery Close", "suite_cutoff", "year", "Response ID", "Confirmation Code",
                           "SessionID", "Survey ID", "entry_id", "dealer_group_id"])

        # Contact data
        header_row.extend(["is_staff", "email", "first_name:contact", "last_name:contact", "Title:contact",
                           "Company Name:contact", "street_address:contact", "apt_suite_office:contact",
                           "city:contact", "state:contact", "zip:contact", "country:contact", "phone:contact",
                           "Mobile Phone:contact"])

        # Entry metadata
        header_row.extend(["Time Started", "Date Submitted", "entry_confirmed", "Status", "edit_link", "I agree:agree",
                           "Comments", "payment_valid", "reg_conf_code", "entry_type", "Referer",
                           "User Agent", "IP Address", "Longitude", "Latitude", "Country", "City", "State/Region",
                           "Postal"])

        # Entry data
        header_row.extend(["group_conf", "group_email", "Yes:age_ack", "special_room", "ada_req_text",
                           "I agree, understand and will comply:suite_agree",
                           "desired_arrival", "latest_arrival", "desired_departure", "earliest_departure"])

        all_hotels = session.query(LotteryHotel).filter_by(active=True).order_by(LotteryHotel.name).all()
        all_room_types = session.query(LotteryRoomType).filter_by(is_suite=False, active=True).order_by(LotteryRoomType.name).all()
        all_suite_types = session.query(LotteryRoomType).filter_by(is_suite=True, active=True).order_by(LotteryRoomType.name).all()

        for hotel in all_hotels:
            header_row.append(f"{hotel.export_name or hotel.name}:hotel_pref")

        for rt in all_room_types:
            header_row.append(f"{rt.export_name or rt.name}:room_pref")

        for st in all_suite_types:
            header_row.append(f"{st.export_name or st.name}:suite_type")

        out.writerow(header_row)

        applications = session.query(LotteryApplication).join(LotteryApplication.attendee
                                                              ).filter(LotteryApplication.status != c.PROCESSED,
                                                                       Attendee.hotel_lottery_eligible == True)
        if staff_lottery:
            applications = applications.filter(LotteryApplication.is_staff_entry == True)
        else:
            applications = applications.filter(LotteryApplication.is_staff_entry == False)

        for app in applications:
            attendee = app.attendee
            row = []

            # Config data and IDs
            dealer_id = ''
            if app.attendee.is_dealer and app.attendee.group and app.attendee.group.status in c.DEALER_ACCEPTED_STATUSES:
                dealer_id = app.attendee.group.id
            current_lottery_deadline = c.HOTEL_LOTTERY_STAFF_DEADLINE if app.is_staff_entry else c.HOTEL_LOTTERY_FORM_DEADLINE
            row.extend([datetime_local_filter(current_lottery_deadline), datetime_local_filter(c.HOTEL_LOTTERY_SUITE_CUTOFF),
                        c.EVENT_YEAR, app.response_id, app.confirmation_num, app.id, "RAMS_1", app.id, dealer_id])

            # Contact data
            base_cellphone = app.cellphone or app.attendee.cellphone
            row.extend([print_bool(attendee.badge_type == c.STAFF_BADGE or c.STAFF_RIBBON in attendee.ribbon_ints),
                        attendee.email, app.legal_first_name or attendee.legal_first_name,
                        app.legal_last_name or attendee.legal_last_name, "", "", attendee.address1,
                        attendee.address2, attendee.city, attendee.region, attendee.zip_code,
                        country_codes.get(attendee.country, attendee.country),
                        ''.join(filter(str.isdigit, base_cellphone)) if base_cellphone else "", ""])

            # Entry metadata
            if app.entry_type:
                type_str = "I am entering as a roommate" if app.entry_type == c.GROUP_ENTRY else "I am requesting a room"
            else:
                type_str = "I am withdrawing from the lottery"
            row.extend([print_dt(app.entry_started), print_dt(app.last_submitted), print_bool(app.status == c.COMPLETE),
                        app.status_label, f"{c.URL_BASE}/hotel_lottery/index?attendee_id={app.attendee.id}",
                        print_bool(app.terms_accepted), app.admin_notes, "FALSE", attendee.id, type_str])
            if app.entry_metadata:
                row.extend([app.entry_metadata.get('referer'), app.entry_metadata.get('user_agent'), app.entry_metadata.get('ip_address')])
            else:
                row.extend(['', '', ''])
            row.extend(['', '', '', '', '', ''])

            # Entry data
            if app.parent_application:
                row.extend([app.parent_application.confirmation_num, app.parent_application.email,
                            '', '', '', '', '', '', '', ''])
            else:
                row.extend(['', '', print_bool(app.entry_form_completed)])

                entry_type_base = app.entry_type or c.ROOM_ENTRY
                if entry_type_base == c.ROOM_ENTRY:
                    if app.wants_ada:
                        row.extend(['ADA Room', app.ada_requests, ''])
                    else:
                        row.extend(['Standard Rooms with no Special Requests', '', ''])
                elif entry_type_base == c.SUITE_ENTRY:
                    row.extend(['Hyatt Regency O\'Hare Suites', '', print_bool(app.suite_terms_accepted)])
                
                row.extend([print_dt(app.earliest_checkin_date), print_dt(app.latest_checkin_date),
                            print_dt(app.latest_checkout_date), print_dt(app.earliest_checkout_date)])

            if app.parent_application or not app.hotel_preference or (
                    app.entry_type and app.entry_type == c.SUITE_ENTRY and app.room_opt_out):
                row.extend(['' for _ in range(len(all_hotels))])
            else:
                hotels_ranking = {}
                for index, item in enumerate(app.hotel_preference.split(','), start=1):
                    hotels_ranking[item] = index

                for hotel in all_hotels:
                    row.append(hotels_ranking.get(str(hotel.id), ''))

            if app.parent_application or not app.room_type_preference or (
                    app.entry_type and app.entry_type == c.SUITE_ENTRY and app.room_opt_out):
                row.extend(['' for _ in range(len(all_room_types))])
            else:
                room_types_ranking = {}
                for index, item in enumerate(app.room_type_preference.split(','), start=1):
                    room_types_ranking[item] = index

                for rt in all_room_types:
                    row.append(room_types_ranking.get(str(rt.id), ''))

            if app.parent_application or not app.suite_type_preference or (
                    app.entry_type and app.entry_type == c.ROOM_ENTRY):
                row.extend(['' for _ in range(len(all_suite_types))])
            else:
                suite_types_ranking = {}
                for index, item in enumerate(app.suite_type_preference.split(','), start=1):
                    suite_types_ranking[item] = index

                for st in all_suite_types:
                    row.append(suite_types_ranking.get(str(st.id), ''))

            out.writerow(row)

    def manage_partitions(self, session, message=''):
        partitions = session.query(InventoryPartition).order_by(InventoryPartition.name).all()

        # Count assigned per partition
        assigned_per_partition = defaultdict(int)
        for app in session.query(LotteryApplication).filter(
            LotteryApplication.status.in_(c.HOTEL_LOTTERY_AWARD_STATUSES),
            LotteryApplication.entry_type != c.GROUP_ENTRY,
            LotteryApplication.assigned_inventory_id != None,
        ).all():
            key = str(app.partition_id) if app.partition_id else '_none'
            assigned_per_partition[key] += 1

        # Compute total allocation and non-partitioned capacity
        total_partition_alloc = 0
        for p in partitions:
            for b in p.blocks:
                total_partition_alloc += b.quantity

        total_inventory = sum(inv.quantity for inv in session.query(HotelRoomInventory).filter_by(active=True).all())

        return {
            'partitions': partitions,
            'assigned_per_partition': assigned_per_partition,
            'non_partitioned_capacity': max(0, total_inventory - total_partition_alloc),
            'message': message,
        }

    def edit_partition(self, session, id=None, message='', **params):
        if id and id not in ('None', ''):
            partition = session.query(InventoryPartition).get(id)
        else:
            partition = None
        if not partition:
            partition = InventoryPartition()

        inventory_blocks = session.query(HotelRoomInventory).filter_by(active=True).order_by(
            HotelRoomInventory.hotel_id, HotelRoomInventory.name).all()
        existing_blocks = {str(pb.inventory_id): pb.quantity for pb in partition.blocks} if partition.id else {}

        if cherrypy.request.method == 'POST':
            partition.name = params.get('name', '').strip()
            partition.description = params.get('description', '').strip()
            partition.active = params.get('active') == 'true'
            session.add(partition)
            session.flush()

            existing_pb = {str(pb.inventory_id): pb for pb in partition.blocks}
            for inv in inventory_blocks:
                qty_str = params.get(f'block_qty_{inv.id}', '')
                if qty_str != '' and int(qty_str) > 0:
                    qty = int(qty_str)
                    if str(inv.id) in existing_pb:
                        existing_pb[str(inv.id)].quantity = qty
                    else:
                        pb = InventoryPartitionBlock(
                            partition_id=partition.id, inventory_id=str(inv.id), quantity=qty)
                        session.add(pb)
                elif str(inv.id) in existing_pb:
                    session.delete(existing_pb[str(inv.id)])

            session.commit()
            raise HTTPRedirect('manage_partitions?message={}', f"Partition '{partition.name}' saved.")

        return {
            'partition': partition,
            'inventory_blocks': inventory_blocks,
            'existing_blocks': existing_blocks,
            'message': message,
        }

    @ajax
    def reduce_awards(self, session, inventory_id, night_date, target_count):
        try:
            target_count = int(target_count)
            night = date.fromisoformat(night_date)
        except (ValueError, TypeError):
            return {"error": "Invalid target count or date."}

        apps = session.query(LotteryApplication).filter(
            LotteryApplication.assigned_inventory_id == inventory_id,
            LotteryApplication.status.in_(c.HOTEL_LOTTERY_AWARD_STATUSES),
            LotteryApplication.entry_type != c.GROUP_ENTRY,
            LotteryApplication.assigned_check_in_date <= night,
            LotteryApplication.assigned_check_out_date > night,
        ).all()

        current_count = len(apps)
        if target_count >= current_count:
            return {"success": True, "message": f"No reduction needed ({current_count} currently assigned)."}

        ejectable = [a for a in apps if not a.group_members]
        if len(ejectable) < current_count - target_count:
            ejectable = apps

        to_eject = random.sample(ejectable, min(len(ejectable), current_count - target_count))

        for app in to_eject:
            app.assigned_inventory_id = None
            app.assigned_check_in_date = None
            app.assigned_check_out_date = None
            app.partition_id = None
            app.status = c.COMPLETE
            app.lottery_name = ''
            app.lottery_run_id = None
            for member in app.group_members:
                member.assigned_inventory_id = None
                member.assigned_check_in_date = None
                member.assigned_check_out_date = None
                member.partition_id = None
                member.status = c.COMPLETE
                member.lottery_name = ''
                member.lottery_run_id = None
                session.add(member)
            session.add(app)

        session.commit()
        return {"success": True, "message": f"Ejected {len(to_eject)} entries. {target_count} remain for {night_date}."}

    @ajax
    def unlock_application(self, session, id):
        app = session.lottery_application(id)
        app.export_locked = False
        session.add(app)
        session.commit()
        return {"success": True}

    @ajax
    def bulk_unlock(self, session, ids):
        id_list = [x.strip() for x in ids.split(',') if x.strip()]
        count = 0
        for app_id in id_list:
            app = session.query(LotteryApplication).get(app_id)
            if app and app.export_locked:
                app.export_locked = False
                session.add(app)
                count += 1
        session.commit()
        return {"success": True, "count": count}

    @ajax
    def process_waitlist(self, session, inventory_id='', night_date=''):
        inv_id = inventory_id if inventory_id else None
        nd = date.fromisoformat(night_date) if night_date else None
        result = _fulfill_waitlist(session, inventory_id=inv_id, night_date=nd)
        return result
