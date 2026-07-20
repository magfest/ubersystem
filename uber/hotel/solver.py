"""Hotel lottery solver engine.

Turns the pool of eligible LotteryApplications plus the available
inventory table into room awards. `solve_lottery` builds an OR-Tools
integer program (per-night capacity, per-app award cap, and mandatory
connector-room coupling) and returns raw allocations;
`materialize_room_assignments` persists those allocations as
RoomAssignment rows (primaries plus connector children, with group
members attached as occupants). The capacity helpers reshape the
inventory table for a run's partition scope before solving.

The web handler (hotel_lottery_admin.run_lottery) stays in charge of
parsing parameters, building the eligible-application query, and
recording the LotteryRun; this module is the portable computation
underneath it.
"""
import logging
import random
from collections import defaultdict
from copy import deepcopy
from datetime import date, timedelta

from ortools.linear_solver import pywraplp
from sqlalchemy import or_

from uber.config import c

log = logging.getLogger(__name__)


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

def solve_lottery(applications, hotel_rooms, lottery_type=c.ROOM_ENTRY,
                  connector_map=None):
    """Takes a set of hotel_rooms and applications and assigns the
    hotel_rooms with mandatory connector-room coupling.

    Each inventory block can be tagged as a "connector" via
    `connector_map`: a dict mapping `child_type_id` ->
    `(parent_type_id, qty)`. Connector inventory does not participate
    in the per-app "max 1 room" cap, but each connector still respects
    its own per-inventory capacity. The solver adds an equality coupling
    constraint per app and parent inventory:

        sum(child_vars for app over child_type inventory)
            == parent_var[app, p] * qty

    so awarding the parent forces exactly `qty` connectors to the same
    app, and a parent cannot be awarded if its connectors can't be
    satisfied.

    Parameters:
        applications List[Application]: Iterable set of Application
            objects to assign.
        hotel_rooms List[dict]: Iterable set of hotel rooms; each dict
            has id, hotel_id, capacity, min_capacity, room_type,
            quantity, night_quantities.
        lottery_type: c.ROOM_ENTRY or c.SUITE_ENTRY.
        connector_map: dict {child_type_id: (parent_type_id, qty)}.
            Empty / None when no types are configured as connectors.

    Returns:
        List[Tuple[application_id, inventory_id, role]] where role is
        'primary' or 'connector'. The same application id can appear
        more than once. Returns None on solver failure.
    """
    connector_map = connector_map or {}
    connector_types = set(connector_map.keys())
    # parent_type -> list of (child_type, qty)
    parent_to_children = {}
    for child_type, (parent_type, qty) in connector_map.items():
        parent_to_children.setdefault(parent_type, []).append((child_type, qty))

    random.shuffle(applications)
    solver = pywraplp.Solver.CreateSolver("SAT")
    solver.SetSolverSpecificParametersAsString("log_search_progress: true")

    # Collect all nights across all inventory blocks.
    all_nights = set()
    inventory_by_id = {hr["id"]: hr for hr in hotel_rooms}
    inventory_by_type = {}  # type_id -> [hotel_room_dict, ...]
    for hr in hotel_rooms:
        hr["primary_constraints"] = []   # [(BoolVar, entry)] for per-app cap + per-inv cap
        hr["connector_constraints"] = []  # [(BoolVar, entry, parent_inv_id)] for per-inv cap only
        if hr.get("night_quantities"):
            all_nights.update(hr["night_quantities"].keys())
        inventory_by_type.setdefault(hr["room_type"], []).append(hr)

    # Build entries (one per non-group app), then absorb group members.
    entries = {}
    for app in applications:
        if app.entry_type == lottery_type or (
                lottery_type == c.ROOM_ENTRY
                and app.entry_type == c.SUITE_ENTRY
                and app.room_opt_out is False):
            type_pref = (app.room_type_preference if lottery_type == c.ROOM_ENTRY
                         else app.suite_type_preference)
            entries[app.id] = {
                "app": app,
                "members": [app],
                "hotels": app.hotel_preference.split(","),
                "room_types": type_pref.split(","),
                "primary_vars": [],     # [(BoolVar, weight, hotel_room)]
                "connector_vars": [],   # [(BoolVar, hotel_room, parent_inv_id, child_type, qty)]
                "check_in": app.earliest_checkin_date,
                "check_out": app.latest_checkout_date,
            }

    for app in applications:
        if app.parent_application and app.parent_application.id in entries:
            entries[app.parent_application.id]["members"].append(app)

    # Create BoolVars: primary for every eligible (app, non-connector inv),
    # plus connector vars for every (app, parent_inv, child_inv) where the
    # app might win the parent.
    for app_id, entry in entries.items():
        # Bias weights based on group size.
        base_weight = 0
        weights_cfg = c.HOTEL_LOTTERY["weights"]
        if random.random() < weights_cfg[f"group_weight_{len(entry['members'])}"]:
            base_weight = weights_cfg[f"group_base_{len(entry['members'])}"]

        for hr in hotel_rooms:
            # An app's preferences only consider primary (non-connector)
            # types. Connector rooms can never be a primary preference.
            if hr["room_type"] in connector_types:
                continue
            if hr["hotel_id"] not in entry["hotels"]:
                continue
            if hr["room_type"] not in entry["room_types"]:
                continue
            if not (hr["min_capacity"] <= len(entry["members"]) <= hr["capacity"]):
                continue

            weight = weight_entry(entry, hr, base_weight)
            primary_var = solver.BoolVar(f'{app_id}_primary_{hr["id"]}')
            entry["primary_vars"].append((primary_var, weight, hr))
            hr["primary_constraints"].append((primary_var, entry))

            # For each child type of this primary's room type, also create
            # connector BoolVars over every child-type inventory. We index
            # by parent_inventory_id so the coupling constraint can be
            # local to (app, parent_inv).
            for child_type, qty in parent_to_children.get(hr["room_type"], []):
                for child_hr in inventory_by_type.get(child_type, []):
                    cvar = solver.BoolVar(
                        f'{app_id}_connector_{child_hr["id"]}_for_{hr["id"]}')
                    entry["connector_vars"].append(
                        (cvar, child_hr, hr["id"], child_type, qty))
                    child_hr["connector_constraints"].append(
                        (cvar, entry, hr["id"]))

    # Per-inventory capacity. Each inventory's pool is the union of its
    # primary BoolVars (apps using it as their main award) plus its
    # connector BoolVars (apps using it as a ride-along for some parent).
    def _vars_for_inventory(hr):
        primary = [(cv, entry) for cv, entry in hr["primary_constraints"]]
        connector = [(cv, entry) for cv, entry, _ in hr["connector_constraints"]]
        return primary + connector

    if all_nights:
        for hr in hotel_rooms:
            inv_vars = _vars_for_inventory(hr)
            if not inv_vars:
                continue
            nq = hr.get("night_quantities", {})
            for night_iso in sorted(all_nights):
                # A night missing from night_quantities falls back to the
                # block's flat quantity (admin form: "leave blank to use
                # the default"); only an explicit 0 closes the night. A
                # block with no per-night data at all must still be
                # capacity-constrained here, or mixed configurations
                # would let the solver award unlimited rooms from it.
                night_qty = nq.get(night_iso, hr["quantity"])
                night_date = date.fromisoformat(night_iso)
                night_vars = [
                    cv for cv, entry in inv_vars
                    if entry["check_in"] and entry["check_out"]
                    and entry["check_in"] <= night_date < entry["check_out"]
                ]
                if not night_vars:
                    continue
                if night_qty <= 0:
                    # Sold-out/closed night: forbid awards outright. A
                    # skipped constraint would leave the night
                    # UNconstrained and let the solver oversubscribe it.
                    solver.Add(sum(night_vars) == 0)
                else:
                    solver.Add(sum(night_vars) <= night_qty)
    else:
        # Fallback when no per-night data is available.
        for hr in hotel_rooms:
            inv_vars = _vars_for_inventory(hr)
            if inv_vars:
                solver.Add(sum(cv for cv, _ in inv_vars) <= hr["quantity"])

    # Per-app "max one primary award" cap. Connector BoolVars are
    # intentionally excluded - connector rooms ride along with the
    # parent and don't count as separate awards.
    for app_id, entry in entries.items():
        if entry["primary_vars"]:
            solver.Add(sum(v for v, _, _ in entry["primary_vars"]) <= 1)

    # Connector coupling. For each (app, parent_inventory, child_type),
    # the sum of connector BoolVars over all inventory of that child
    # type for that (app, parent_inv) must equal qty if the parent is
    # awarded, and 0 otherwise. We express this as a single equality
    # constraint per (app, parent_inv, child_type).
    for app_id, entry in entries.items():
        # Bucket connector vars by (parent_inv_id, child_type, qty).
        bucket = {}  # (parent_inv_id, child_type) -> (qty, [child_vars])
        for cvar, child_hr, parent_inv_id, child_type, qty in entry["connector_vars"]:
            bucket.setdefault((parent_inv_id, child_type), (qty, []))
            bucket[(parent_inv_id, child_type)][1].append(cvar)

        for (parent_inv_id, child_type), (qty, cvars) in bucket.items():
            # Find the parent BoolVar for this app and parent inventory.
            parent_var = None
            for pvar, _w, hr in entry["primary_vars"]:
                if hr["id"] == parent_inv_id:
                    parent_var = pvar
                    break
            if parent_var is None or not cvars:
                continue
            # sum(connectors) == parent * qty
            solver.Add(sum(cvars) == parent_var * qty)

    # Objective: weighted sum on primary BoolVars only. Connectors ride
    # along and don't contribute to the maximization signal.
    objective = solver.Objective()
    for entry in entries.values():
        for pvar, weight, _hr in entry["primary_vars"]:
            objective.SetCoefficient(pvar, weight)
    objective.SetMaximization()

    status = solver.Solve()
    if status not in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE):
        log.error(f"Error solving room lottery: {status}")
        return None

    # Output: list of (leader_application_id, inventory_id, role). Group
    # members do NOT appear separately - they get added as occupants on
    # each leader-owned RoomAssignment during materialization.
    allocations = []
    for app_id, entry in entries.items():
        leader_id = entry["app"].id
        for pvar, _weight, hr in entry["primary_vars"]:
            if pvar.solution_value() > 0.5:
                allocations.append((leader_id, hr["id"], 'primary'))

        for cvar, child_hr, _pid, _ct, _qty in entry["connector_vars"]:
            if cvar.solution_value() > 0.5:
                allocations.append((leader_id, child_hr["id"], 'connector'))

    return allocations


def build_eligible_applications(session, lottery_type_val, lottery_group,
                                cutoff=None, confirmation_window_start=None):
    """The pool of applications a lottery run considers: COMPLETE entries
    whose attendee is lottery-eligible, optionally gated by a submission
    cutoff and a re-confirmation window (when set, only apps whose
    attendee has clicked Confirm since that datetime are considered -
    apps that were awarded and then expired sit in COMPLETE and must
    re-confirm when the admin sets this filter).

    We always grab all roommate entries, but the solver only looks at
    those that have a matching parent in the lottery batch. If
    lottery_group is "both" we don't filter staff/attendee either way.
    """
    from uber.models import Attendee, LotteryApplication

    applications = session.query(LotteryApplication).join(LotteryApplication.attendee
                                                          ).filter(LotteryApplication.status == c.COMPLETE,
                                                                   Attendee.hotel_lottery_eligible == True)  # noqa: E712

    if cutoff:
        applications = applications.filter(LotteryApplication.last_submitted < cutoff)

    if confirmation_window_start:
        applications = applications.filter(
            LotteryApplication.last_confirmed_at.isnot(None),
            LotteryApplication.last_confirmed_at >= confirmation_window_start,
        )

    if lottery_type_val == c.SUITE_ENTRY:
        applications = applications.filter(LotteryApplication.entry_type.in_([lottery_type_val, c.GROUP_ENTRY]))
    else:
        applications = applications.filter(or_(LotteryApplication.entry_type.in_([lottery_type_val, c.GROUP_ENTRY]),
                                               LotteryApplication.room_opt_out == False))  # noqa: E712

    if lottery_group == "staff":
        applications = applications.filter(LotteryApplication.is_staff_entry == True)  # noqa: E712
    elif lottery_group == "attendee":
        applications = applications.filter(LotteryApplication.is_staff_entry == False)  # noqa: E712

    return applications.all()


def filter_inventory_table(inventory_table, hotel_filter='',
                           room_type_filter='', inventory_filter=''):
    """Narrow the inventory table to the run's hotel / room-type /
    inventory-block filters (each a comma-separated id string, empty for
    no filter)."""
    if hotel_filter:
        hotel_filter_set = set(hotel_filter.split(','))
        inventory_table = [r for r in inventory_table if r['hotel_id'] in hotel_filter_set]
    if room_type_filter:
        room_type_filter_set = set(room_type_filter.split(','))
        inventory_table = [r for r in inventory_table if r['room_type'] in room_type_filter_set]
    if inventory_filter:
        inventory_filter_set = set(inventory_filter.split(','))
        inventory_table = [r for r in inventory_table if r['id'] in inventory_filter_set]
    return inventory_table


def count_assigned_per_block_night(already_assigned):
    """Count already-assigned rooms per inventory block per night from a
    list of RoomAssignment rows. Connector rooms count against their own
    inventory's capacity; primary rooms count against theirs - both are
    RoomAssignment rows.

    Thin wrapper over the canonical histogram in uber.hotel.queries,
    keyed the way the solver's interchange format expects:
    {inventory_id: {night_iso: count}}.
    """
    from uber.hotel.queries import occupancy_by_block_night
    return occupancy_by_block_night(already_assigned, iso_keys=True)


def adjust_available_rooms(inventory_table, partition_filter,
                           partition_qty_map, total_partitioned_map,
                           assigned_per_block_night):
    """Reshape the inventory table into the room availability the solver
    should see for this run: cap each block at the selected partition's
    allocation (or subtract every partition's carve-out for a
    non-partitioned run), then subtract the rooms already assigned per
    block/night. Returns a deep copy; the input table is not mutated.
    """
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

    return available_rooms


def _set_occupants(session, assignment, attendee_ids):
    """Replace the room_assignment_occupant rows for `assignment`."""
    from uber.models.hotel import room_assignment_occupant
    session.execute(room_assignment_occupant.delete().where(
        room_assignment_occupant.c.room_assignment_id == assignment.id))
    for aid in attendee_ids:
        session.execute(room_assignment_occupant.insert().values(
            room_assignment_id=assignment.id, attendee_id=aid))


def materialize_room_assignments(session, applications, allocations,
                                 lottery_run, run_deadline, partition_filter):
    """Create RoomAssignment rows for the solver output.

    `allocations` is the list of (leader_application_id, inventory_id,
    role) tuples produced by solve_lottery. Group members are added as
    occupants on each leader-owned RoomAssignment.

    Connector rows are created with parent_assignment_id pointing at
    the primary RoomAssignment for the same (app, parent_inventory).
    Each connector lives as its own row so the hotel export emits one
    line per physical room.

    Returns the number of distinct leaders that got at least one
    primary award (so the caller can stamp lottery_run.rooms_assigned).
    """
    from uber.models import RoomAssignment

    app_by_id = {a.id: a for a in applications}

    # Group allocations by leader app + role.
    by_leader = {}  # leader_id -> {'primary': [inv_id...], 'connector': [inv_id...]}
    for leader_id, inv_id, role in allocations:
        by_leader.setdefault(leader_id, {'primary': [], 'connector': []})[role].append(inv_id)

    leaders_with_primary = 0
    for leader_id, roles in by_leader.items():
        leader = app_by_id.get(leader_id)
        if not leader or not leader.attendee_id:
            continue

        # Default occupants: the leader's attendee + every valid group
        # member's attendee. Leaders edit per-room later.
        occupant_ids = [leader.attendee_id]
        for member in leader.valid_group_members or []:
            if member.attendee_id and member.attendee_id not in occupant_ids:
                occupant_ids.append(member.attendee_id)

        # Primary first so we can hang connectors off its id.
        primaries_by_inv = {}
        for inv_id in roles['primary']:
            primary = RoomAssignment(
                attendee_id=leader.attendee_id,
                inventory_id=inv_id,
                lottery_application_id=leader.id,
                lottery_run_id=lottery_run.id,
                partition_id=partition_filter or None,
                assignment_reason=c.LOTTERY_AWARD,
                status=c.ASSIGNED,
                require_cc=True,
                assigned_check_in_date=leader.earliest_checkin_date,
                assigned_check_out_date=leader.latest_checkout_date,
                deposit_cutoff_date=run_deadline,
            )
            session.add(primary)
            session.flush()  # need primary.id
            primaries_by_inv[inv_id] = primary
            _set_occupants(session, primary, occupant_ids)
            leaders_with_primary += 1

        # Connectors - for each, find the parent primary in this leader's
        # set (any primary will do as the structural parent; the solver's
        # coupling already guaranteed there's one).
        parent_primary = next(iter(primaries_by_inv.values()), None)
        for inv_id in roles['connector']:
            child = RoomAssignment(
                attendee_id=leader.attendee_id,
                inventory_id=inv_id,
                lottery_application_id=leader.id,
                lottery_run_id=lottery_run.id,
                parent_assignment_id=parent_primary.id if parent_primary else None,
                partition_id=partition_filter or None,
                assignment_reason=c.SUITE_CONNECTOR,
                status=c.ASSIGNED,
                require_cc=True,
                assigned_check_in_date=leader.earliest_checkin_date,
                assigned_check_out_date=leader.latest_checkout_date,
                deposit_cutoff_date=run_deadline,
            )
            session.add(child)
            session.flush()
            _set_occupants(session, child, occupant_ids)

    return leaders_with_primary
