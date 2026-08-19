"""Partition-scoped admin dashboard.

Accessible to AdminAccounts with at least one PartitionOwner grant (the
section gate in has_section_or_page_access). Each request is further
gated by uber.hotel.perms helpers against the specific partition_id.

The four owner departments (Marketplace, Belvedere, Panels, Accessibility)
land here to manage their exhibitor / panelist / ADA rooms without
touching the broader hotel_lottery_admin pages.
"""

from collections import Counter, defaultdict
import logging

import cherrypy
from sqlalchemy import func
from sqlalchemy.orm import joinedload

from uber.config import c
from uber.decorators import all_renderable, ajax_gettable
from uber.errors import HTTPRedirect
from uber.hotel.queries import (attendee_search_results,
                                build_room_assignment_query, paginate)
from uber.hotel.service import (
    RoomAssignmentError, apply_room_assignment_edits, create_room_assignment,
)
from uber.hotel.perms import (
    can_edit_assignments_in,
    can_edit_inventory_in,
    can_view_assignments_in,
    can_view_guest_legal_names,
    can_view_guest_names_in,
    can_view_inventory_in,
    is_lottery_admin,
    record_partition_audit,
    requires_partition_capability,
)
from uber.models import AdminAccount
from uber.models.hotel import (
    HotelRoomInventory, InventoryPartition, InventoryPartitionBlock,
    PartitionAuditLog, PartitionOwner, RoomAssignment,
)
from uber.utils import check_csrf


log = logging.getLogger(__name__)

PAGE_SIZE = 50


def _partitions_for_current_admin(session):
    """Partitions the current admin can see - all if lottery admin,
    otherwise only those they have a PartitionOwner row for."""
    if is_lottery_admin():
        return session.query(InventoryPartition).filter_by(active=True).order_by(
            InventoryPartition.name).all()
    account_id = cherrypy.session.get('account_id') if cherrypy.session else None
    if not account_id:
        return []
    grants = session.query(PartitionOwner).filter_by(
        admin_account_id=account_id).all()
    partition_ids = [g.partition_id for g in grants]
    if not partition_ids:
        return []
    return session.query(InventoryPartition).filter(
        InventoryPartition.id.in_(partition_ids)).order_by(InventoryPartition.name).all()


def _partition_block_inventory_ids(session, partition_id):
    """Inventory ids allocated to this partition via its blocks.

    Server-side bound for every inventory_id a partition-scoped route will
    accept: without it, a partition owner could point an assignment at the
    main lottery's (or another partition's) inventory and corrupt the
    capacity accounting, which counts by (partition, inventory) pair.
    """
    return {b.inventory_id
            for b in session.query(InventoryPartitionBlock)
            .filter_by(partition_id=str(partition_id)).all()
            if b.inventory_id}


@all_renderable()
class Root:
    def index(self, session, message=''):
        """List of partitions the current admin can act on."""
        partitions = _partitions_for_current_admin(session)
        partition_ids = [str(p.id) for p in partitions]

        # One grouped query for every partition's status counts and one
        # IN query for the blocks, instead of two queries per partition.
        status_counts = {}
        quantity_by_partition = defaultdict(int)
        if partition_ids:
            for pid, status, n in (
                    session.query(RoomAssignment.partition_id,
                                  RoomAssignment.status,
                                  func.count(RoomAssignment.id))
                    .filter(RoomAssignment.partition_id.in_(partition_ids))
                    .group_by(RoomAssignment.partition_id,
                              RoomAssignment.status)):
                status_counts[(str(pid), status)] = n
            for b in session.query(InventoryPartitionBlock).filter(
                    InventoryPartitionBlock.partition_id.in_(partition_ids)):
                quantity_by_partition[str(b.partition_id)] += b.quantity

        rows = []
        for p in partitions:
            pid = str(p.id)
            rows.append({
                'partition': p,
                'total_quantity': quantity_by_partition[pid],
                'assigned': status_counts.get((pid, c.ASSIGNED), 0),
                'secured': status_counts.get((pid, c.SECURED), 0),
                'cancelled': status_counts.get((pid, c.CANCELLED), 0),
                'expired': status_counts.get((pid, c.EXPIRED), 0),
            })
        return {'rows': rows, 'message': message}

    @requires_partition_capability('view')
    def dashboard(self, session, partition_id, tab='inventory',
                  page='1', activity_page='1', message=''):
        """Per-partition view, tabbed: inventory / assignments / activity.

        Inventory tab - all blocks with allocated/assigned/secured/unassigned
        counts + a totals row.
        Assignments tab - paginated roster + assign-room form (with attendee
        search). Each row has an Edit button that opens a modal showing every
        room assigned to that attendee, all editable.
        Activity tab - paginated audit log.
        """
        partition = session.query(InventoryPartition).get(partition_id)
        if not partition:
            raise HTTPRedirect('index?message={}', 'Partition not found.')

        # Per-tab gating: an inventory-only grant must not see the roster,
        # and vice versa. The activity log is available to anyone who
        # passed the view gate (requires_partition_capability above).
        can_view_inventory = can_view_inventory_in(session, partition_id)
        can_view_assignments = can_view_assignments_in(session, partition_id)
        allowed_tabs = ['activity']
        if can_view_assignments:
            allowed_tabs.insert(0, 'assignments')
        if can_view_inventory:
            allowed_tabs.insert(0, 'inventory')
        if tab not in allowed_tabs:
            tab = allowed_tabs[0]

        blocks = []
        totals = {'allocated': 0, 'assigned': 0, 'secured': 0, 'unassigned': 0}
        partition_blocks = partition.blocks if can_view_inventory else []

        # One grouped query for the whole partition's per-block counts
        # instead of one RoomAssignment query per block.
        live_by_inv, secured_by_inv = defaultdict(int), defaultdict(int)
        if partition_blocks:
            for inv_id, status, n in (
                    session.query(RoomAssignment.inventory_id,
                                  RoomAssignment.status,
                                  func.count(RoomAssignment.id))
                    .filter(RoomAssignment.partition_id == partition.id)
                    .group_by(RoomAssignment.inventory_id,
                              RoomAssignment.status)):
                key = str(inv_id) if inv_id else None
                if status in c.HOTEL_LIVE_ASSIGNMENT_STATUSES:
                    live_by_inv[key] += n
                if status == c.SECURED:
                    secured_by_inv[key] += n

        for b in partition_blocks:
            inv = b.inventory
            assigned = live_by_inv[str(inv.id)] if inv else 0
            secured = secured_by_inv[str(inv.id)] if inv else 0
            unassigned = max(0, b.quantity - assigned)
            blocks.append({
                'block': b,
                'inventory': inv,
                'assigned': assigned,
                'secured': secured,
                'unassigned': unassigned,
            })
            totals['allocated'] += b.quantity
            totals['assigned'] += assigned
            totals['secured'] += secured
            totals['unassigned'] += unassigned

        # Shared query layer: partition-scoped roster, every status
        # (partition owners manage their full list, not just live rows).
        roster_q = build_room_assignment_query(
            session, status='all', partition_id=str(partition.id)).order_by(
            RoomAssignment.status.asc(),
            RoomAssignment.assigned_check_in_date.asc().nullsfirst(),
            RoomAssignment.created.asc())
        if can_view_assignments:
            roster, roster_total, page, last_page = paginate(
                roster_q, page, PAGE_SIZE)
        else:
            roster, roster_total, page, last_page = [], roster_q.count(), 1, 1

        # All assignments for the attendees showing on this page (so the
        # edit modal can show every room they hold, not just this
        # partition's view).
        attendee_ids = list({ra.attendee_id for ra in roster if ra.attendee_id})
        if attendee_ids:
            modal_assignments = session.query(RoomAssignment).filter(
                RoomAssignment.attendee_id.in_(attendee_ids)
            ).order_by(
                RoomAssignment.assigned_check_in_date.asc().nullsfirst()
            ).all()
        else:
            modal_assignments = []
        modal_groups = defaultdict(list)
        for ra in modal_assignments:
            modal_groups[ra.attendee_id].append(ra)

        # Eager-load the actor and subject so the activity table doesn't
        # issue a query per row.
        activity_q = session.query(PartitionAuditLog).options(
            joinedload(PartitionAuditLog.attendee),
            joinedload(PartitionAuditLog.admin_account)
            .joinedload(AdminAccount.attendee),
        ).filter_by(partition_id=partition.id).order_by(
            PartitionAuditLog.when.desc())
        activity, activity_total, activity_page, activity_last_page = \
            paginate(activity_q, activity_page, PAGE_SIZE)

        all_status_rows = session.query(
            RoomAssignment.status, RoomAssignment.require_cc).filter_by(
            partition_id=partition.id).all()
        status_counts = Counter(s for s, _ in all_status_rows)
        billing_counts = Counter(
            ('require_cc' if rc else 'master_bill')
            for s, rc in all_status_rows
            if s in c.HOTEL_LIVE_ASSIGNMENT_STATUSES)

        # Inventory the modals' block-picker can pivot to: only active rows
        # allocated to THIS partition via a block. update_assignment and
        # assign_room enforce the same bound server-side.
        block_inv_ids = _partition_block_inventory_ids(session, partition.id)
        if block_inv_ids:
            all_inventory = session.query(HotelRoomInventory).filter(
                HotelRoomInventory.id.in_(block_inv_ids),
                HotelRoomInventory.active.is_(True)).order_by(
                HotelRoomInventory.hotel_id, HotelRoomInventory.name).all()
        else:
            all_inventory = []

        return {
            'partition': partition,
            'tab': tab,
            'can_view_inventory': can_view_inventory,
            'can_view_assignments': can_view_assignments,
            'blocks': blocks,
            'inventory_totals': totals,
            'roster': roster,
            'roster_total': roster_total,
            'page': page,
            'last_page': last_page,
            'modal_groups': dict(modal_groups),
            'all_inventory': all_inventory,
            'activity': activity,
            'activity_total': activity_total,
            'activity_page': activity_page,
            'activity_last_page': activity_last_page,
            'page_size': PAGE_SIZE,
            'status_counts': status_counts,
            'billing_counts': billing_counts,
            'can_edit_assignments': can_edit_assignments_in(session, partition_id),
            'can_edit_inventory': can_edit_inventory_in(session, partition_id),
            'can_view_guest_names': can_view_guest_names_in(session, partition_id),
            'can_view_guest_legal_names': can_view_guest_legal_names(session, partition_id),
            'message': message,
        }

    @requires_partition_capability('can_edit_assignments')
    def toggle_billing(self, session, assignment_id, csrf_token=None):
        """Flip RoomAssignment.require_cc within a partition."""
        if cherrypy.request.method != 'POST':
            raise HTTPRedirect('index')
        check_csrf(csrf_token)
        assignment = session.query(RoomAssignment).get(assignment_id)
        if not assignment:
            raise HTTPRedirect('index?message={}', 'Assignment not found.')

        assignment.require_cc = not assignment.require_cc
        session.add(assignment)
        record_partition_audit(
            session, assignment.partition_id,
            action='assignment.billing_flipped',
            description=("Switched to self-pay (CC required)" if assignment.require_cc
                         else "Switched to master bill")
                        + f": {assignment.room_summary}",
            target_type='assignment', target_id=assignment.id,
            attendee_id=assignment.attendee_id)
        session.commit()
        raise HTTPRedirect(
            'dashboard?partition_id={}&tab=assignments&message={}',
            assignment.partition_id,
            f"Billing for this assignment is now "
            f"{'self-pay (CC required)' if assignment.require_cc else 'master bill'}.")

    @requires_partition_capability('can_edit_assignments')
    def assign_room(self, session, partition_id, attendee_id='',
                    inventory_id='', csrf_token=None, **params):
        """Partition-scoped manual assignment (PARTITION_GRANT)."""
        if cherrypy.request.method != 'POST':
            raise HTTPRedirect(
                'dashboard?partition_id={}&tab=assignments', partition_id)
        check_csrf(csrf_token)

        if not attendee_id or not inventory_id:
            raise HTTPRedirect(
                'dashboard?partition_id={}&tab=assignments&message={}',
                partition_id, 'Attendee and inventory are required.')

        try:
            create_room_assignment(
                session,
                attendee_id=attendee_id,
                inventory_id=inventory_id,
                partition_id=partition_id,
                assignment_reason=c.PARTITION_GRANT,
                status=c.ASSIGNED,
                require_cc=params.get('require_cc') == 'true',
                assigned_check_in_date=params.get('assigned_check_in_date', ''),
                assigned_check_out_date=params.get('assigned_check_out_date', ''),
                enforce_partition_block=True,
                audit_description=f"Assigned room to attendee {attendee_id}",
            )
        except RoomAssignmentError as e:
            raise HTTPRedirect(
                'dashboard?partition_id={}&tab=assignments&message={}',
                partition_id, e.message)
        session.commit()
        raise HTTPRedirect(
            'dashboard?partition_id={}&tab=assignments&message={}',
            partition_id, 'Assignment created.')

    @requires_partition_capability('can_edit_assignments',
                                   message="You don't have permission to edit "
                                           "this assignment.")
    def update_assignment(self, session, assignment_id, csrf_token=None, **params):
        """Edit fields on a single RoomAssignment (from the modal).

        Editable: inventory_id, require_cc, assigned_check_in_date,
        assigned_check_out_date. Per-row permission check against the
        assignment's current partition.
        """
        if cherrypy.request.method != 'POST':
            raise HTTPRedirect('index')
        check_csrf(csrf_token)
        assignment = session.query(RoomAssignment).get(assignment_id)
        if not assignment:
            raise HTTPRedirect('index?message={}', 'Assignment not found.')

        target_partition = assignment.partition_id

        def fail(msg):
            raise HTTPRedirect(
                'dashboard?partition_id={}&tab=assignments&message={}',
                target_partition, msg)

        msg = apply_room_assignment_edits(
            session, assignment, params,
            audit_prefix='Updated', fail=fail,
            allowed_inventory_ids=_partition_block_inventory_ids(
                session, target_partition))
        session.commit()

        raise HTTPRedirect(
            'dashboard?partition_id={}&tab=assignments&message={}',
            target_partition, msg)

    @requires_partition_capability('can_edit_assignments',
                                   message="You don't have permission to remove "
                                           "assignments in this partition.")
    def unassign(self, session, assignment_id, csrf_token=None):
        if cherrypy.request.method != 'POST':
            raise HTTPRedirect('index')
        check_csrf(csrf_token)
        assignment = session.query(RoomAssignment).get(assignment_id)
        if not assignment:
            raise HTTPRedirect('index?message={}', 'Assignment not found.')

        partition_id = assignment.partition_id
        record_partition_audit(
            session, partition_id,
            action='assignment.removed',
            description=f"Removed assignment: {assignment.room_summary}",
            target_type='assignment', target_id=assignment.id,
            attendee_id=assignment.attendee_id)
        session.delete(assignment)
        session.commit()
        raise HTTPRedirect(
            'dashboard?partition_id={}&tab=assignments&message={}',
            partition_id, 'Assignment removed.')

    @ajax_gettable
    def search_attendees(self, session, partition_id, q='', **params):
        """JSON helper for the assign-room attendee picker.

        Result shaping lives in uber.hotel.queries.attendee_search_results;
        this route just adds the partition gate. (Kept inline rather than
        via requires_partition_capability because ajax endpoints return
        an empty JSON list on failure, not a redirect.)
        """
        if not can_edit_assignments_in(session, partition_id):
            return []
        return attendee_search_results(session, q)
