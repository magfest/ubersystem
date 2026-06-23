"""Partition-scoped admin dashboard.

Accessible to AdminAccounts with at least one PartitionOwner grant (the
section gate in has_section_or_page_access). Each request is further
gated by uber.lottery_perms helpers against the specific partition_id.

The four owner departments (Marketplace, Belvedere, Panels, Accessibility)
land here to manage their exhibitor / panelist / ADA rooms without
touching the broader hotel_lottery_admin pages.
"""

from collections import Counter, defaultdict
from datetime import date, datetime
import logging

import cherrypy
import sqlalchemy as sa
from pytz import UTC

from uber.config import c
from uber.decorators import all_renderable, ajax_gettable
from uber.errors import HTTPRedirect
from uber.lottery_perms import (
    can_edit_assignments_in,
    can_edit_inventory_in,
    can_view_assignments_in,
    can_view_guest_legal_names,
    can_view_guest_names_in,
    can_view_inventory_in,
    is_lottery_admin,
    record_partition_audit,
)
from uber.models import Attendee
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


def _gate_view(session, partition_id):
    if not can_view_assignments_in(session, partition_id) and \
            not can_view_inventory_in(session, partition_id):
        raise HTTPRedirect('index?message={}',
                           "You don't have access to that partition.")


def _paginate(query, page):
    """Return (rows, total_count, page) where page is clamped to a valid value."""
    total = query.count()
    last_page = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(1, min(page, last_page))
    rows = query.offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE).all()
    return rows, total, page, last_page


@all_renderable()
class Root:
    def index(self, session, message=''):
        """List of partitions the current admin can act on."""
        partitions = _partitions_for_current_admin(session)
        rows = []
        for p in partitions:
            total_quantity = sum(b.quantity for b in p.blocks)
            assignment_counts = Counter(
                row[0] for row in session.query(RoomAssignment.status).filter_by(
                    partition_id=p.id).all())
            rows.append({
                'partition': p,
                'total_quantity': total_quantity,
                'assigned': assignment_counts.get(c.ASSIGNED, 0),
                'secured': assignment_counts.get(c.SECURED, 0),
                'cancelled': assignment_counts.get(c.CANCELLED, 0),
                'expired': assignment_counts.get(c.EXPIRED, 0),
            })
        return {'rows': rows, 'message': message}

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
        _gate_view(session, partition_id)
        partition = session.query(InventoryPartition).get(partition_id)
        if not partition:
            raise HTTPRedirect('index?message={}', 'Partition not found.')

        try:
            page = int(page or 1)
        except (TypeError, ValueError):
            page = 1
        try:
            activity_page = int(activity_page or 1)
        except (TypeError, ValueError):
            activity_page = 1

        blocks = []
        totals = {'allocated': 0, 'assigned': 0, 'secured': 0, 'unassigned': 0}
        for b in partition.blocks:
            inv = b.inventory
            block_assignments = session.query(RoomAssignment).filter_by(
                partition_id=partition.id,
                inventory_id=inv.id if inv else None,
            ).all() if inv else []
            assigned = sum(1 for ra in block_assignments
                           if ra.status in (c.ASSIGNED, c.SECURED))
            secured = sum(1 for ra in block_assignments
                          if ra.status == c.SECURED)
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

        roster_q = session.query(RoomAssignment).filter_by(
            partition_id=partition.id).order_by(
            RoomAssignment.status.asc(),
            RoomAssignment.assigned_check_in_date.asc().nullsfirst(),
            RoomAssignment.created.asc())
        roster, roster_total, page, last_page = _paginate(roster_q, page)

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

        activity_q = session.query(PartitionAuditLog).filter_by(
            partition_id=partition.id).order_by(
            PartitionAuditLog.when.desc())
        activity, activity_total, activity_page, activity_last_page = \
            _paginate(activity_q, activity_page)

        all_status_rows = session.query(
            RoomAssignment.status, RoomAssignment.require_cc).filter_by(
            partition_id=partition.id).all()
        status_counts = Counter(s for s, _ in all_status_rows)
        billing_counts = Counter(
            ('require_cc' if rc else 'master_bill')
            for s, rc in all_status_rows
            if s in (c.ASSIGNED, c.SECURED))

        # Inventory the modals' block-picker can pivot to. Restrict to
        # active rows; the modal further filters down to blocks in
        # partitions the editor has access to.
        all_inventory = session.query(HotelRoomInventory).filter_by(
            active=True).order_by(
            HotelRoomInventory.hotel_id, HotelRoomInventory.name).all()

        return {
            'partition': partition,
            'tab': tab if tab in ('inventory', 'assignments', 'activity') else 'inventory',
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

    def toggle_billing(self, session, assignment_id, csrf_token=None):
        """Flip RoomAssignment.require_cc within a partition."""
        if cherrypy.request.method != 'POST':
            raise HTTPRedirect('index')
        check_csrf(csrf_token)
        assignment = session.query(RoomAssignment).get(assignment_id)
        if not assignment:
            raise HTTPRedirect('index?message={}', 'Assignment not found.')

        if not can_edit_assignments_in(session, assignment.partition_id):
            raise HTTPRedirect(
                'dashboard?partition_id={}&tab=assignments&message={}',
                assignment.partition_id,
                "You don't have permission to edit assignments in this partition.")

        assignment.require_cc = not assignment.require_cc
        session.add(assignment)
        record_partition_audit(
            session, assignment.partition_id,
            action='assignment.billing_flipped',
            description=("Switched to self-pay (CC required)" if assignment.require_cc
                         else "Switched to master bill"),
            target_type='assignment', target_id=assignment.id)
        session.commit()
        raise HTTPRedirect(
            'dashboard?partition_id={}&tab=assignments&message={}',
            assignment.partition_id,
            f"Billing for this assignment is now "
            f"{'self-pay (CC required)' if assignment.require_cc else 'master bill'}.")

    def assign_room(self, session, partition_id, attendee_id='',
                    inventory_id='', csrf_token=None, **params):
        """Partition-scoped manual assignment (PARTITION_GRANT)."""
        if cherrypy.request.method != 'POST':
            raise HTTPRedirect(
                'dashboard?partition_id={}&tab=assignments', partition_id)
        check_csrf(csrf_token)

        if not can_edit_assignments_in(session, partition_id):
            raise HTTPRedirect(
                'dashboard?partition_id={}&tab=assignments&message={}',
                partition_id,
                "You don't have permission to edit assignments in this partition.")

        if not attendee_id or not inventory_id:
            raise HTTPRedirect(
                'dashboard?partition_id={}&tab=assignments&message={}',
                partition_id, 'Attendee and inventory are required.')

        ra = RoomAssignment(
            attendee_id=attendee_id,
            inventory_id=inventory_id,
            partition_id=partition_id,
            assignment_reason=c.PARTITION_GRANT,
            status=c.ASSIGNED,
            require_cc=params.get('require_cc') == 'true',
        )
        ci = params.get('assigned_check_in_date', '').strip()
        co = params.get('assigned_check_out_date', '').strip()
        if ci:
            try:
                ra.assigned_check_in_date = date.fromisoformat(ci)
            except ValueError:
                pass
        if co:
            try:
                ra.assigned_check_out_date = date.fromisoformat(co)
            except ValueError:
                pass
        session.add(ra)
        session.flush()
        record_partition_audit(
            session, partition_id,
            action='assignment.created',
            description=f"Assigned room to attendee {attendee_id}",
            target_type='assignment', target_id=ra.id)
        session.commit()
        raise HTTPRedirect(
            'dashboard?partition_id={}&tab=assignments&message={}',
            partition_id, 'Assignment created.')

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
        if not can_edit_assignments_in(session, target_partition):
            raise HTTPRedirect(
                'dashboard?partition_id={}&tab=assignments&message={}',
                target_partition,
                "You don't have permission to edit this assignment.")

        # Track changes for the audit log.
        changes = []
        new_inventory = params.get('inventory_id', '').strip()
        if new_inventory and new_inventory != assignment.inventory_id:
            changes.append('block')
            assignment.inventory_id = new_inventory
        new_require_cc = params.get('require_cc') == 'true'
        if new_require_cc != assignment.require_cc:
            changes.append('billing')
            assignment.require_cc = new_require_cc

        ci = params.get('assigned_check_in_date', '').strip()
        co = params.get('assigned_check_out_date', '').strip()
        try:
            new_ci = date.fromisoformat(ci) if ci else None
        except ValueError:
            new_ci = assignment.assigned_check_in_date
        try:
            new_co = date.fromisoformat(co) if co else None
        except ValueError:
            new_co = assignment.assigned_check_out_date
        if new_ci != assignment.assigned_check_in_date:
            changes.append('check-in')
            assignment.assigned_check_in_date = new_ci
        if new_co != assignment.assigned_check_out_date:
            changes.append('check-out')
            assignment.assigned_check_out_date = new_co

        if changes:
            session.add(assignment)
            record_partition_audit(
                session, target_partition,
                action='assignment.updated',
                description=f"Updated {', '.join(changes)}",
                target_type='assignment', target_id=assignment.id)
            session.commit()
            msg = f"Updated {', '.join(changes)}."
        else:
            msg = 'No changes.'

        raise HTTPRedirect(
            'dashboard?partition_id={}&tab=assignments&message={}',
            target_partition, msg)

    def unassign(self, session, assignment_id, csrf_token=None):
        if cherrypy.request.method != 'POST':
            raise HTTPRedirect('index')
        check_csrf(csrf_token)
        assignment = session.query(RoomAssignment).get(assignment_id)
        if not assignment:
            raise HTTPRedirect('index?message={}', 'Assignment not found.')

        partition_id = assignment.partition_id
        if not can_edit_assignments_in(session, partition_id):
            raise HTTPRedirect(
                'dashboard?partition_id={}&tab=assignments&message={}',
                partition_id,
                "You don't have permission to remove assignments in this partition.")

        record_partition_audit(
            session, partition_id,
            action='assignment.removed',
            description=f"Removed assignment {assignment.id}",
            target_type='assignment', target_id=assignment.id)
        session.delete(assignment)
        session.commit()
        raise HTTPRedirect(
            'dashboard?partition_id={}&tab=assignments&message={}',
            partition_id, 'Assignment removed.')

    @ajax_gettable
    def search_attendees(self, session, partition_id, q='', **params):
        """JSON helper for the assign-room attendee picker.

        Reuses Session.search() so every field the normal admin search
        covers (names, legal name, email, badge ID, badge number, UUID,
        promo group, etc.) works here too.
        """
        if not can_edit_assignments_in(session, partition_id):
            return []
        q = (q or '').strip()
        if len(q) < 2:
            return []

        try:
            results, _ = session.search(q)
        except Exception:
            return []

        out = []
        for a in results.limit(25).all():
            badge = ''
            try:
                badge = str(a.badge_num) if a.badge_num else ''
            except Exception:
                pass
            out.append({
                'id': a.id,
                'name': a.full_name,
                'email': a.email or '',
                'badge_num': badge,
                'badge_type': a.badge_type_label or '',
            })
        return out
