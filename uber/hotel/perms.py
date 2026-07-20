"""Lottery permission helpers.

The hotel lottery has two layers of access:

1. **Global lottery admin** - anyone with HAS_HOTEL_LOTTERY_ADMIN_ACCESS (the
   existing site-section permission). Short-circuits every check to True;
   can edit anything, create/delete partitions, grant PartitionOwner rows.
2. **Partition owner** - an AdminAccount with a PartitionOwner row for a
   specific InventoryPartition, scoped to that partition's blocks and the
   RoomAssignment rows tagged with that partition_id. Each row carries
   independently-toggleable capability flags (see PartitionOwner model).

Plus one stand-alone fine-grained permission:
- `AdminAccount.view_guest_legal_names` - an account-level bool that lets a
  partition owner see attendees' legal names, but only within the partitions
  they own (it has no effect outside their assigned partitions). Global
  lottery admins always see legal names everywhere.

Helper functions accept an explicit `admin_account` (for testing or bulk ops)
or resolve from the current cherrypy session.
"""

import functools
import inspect

import cherrypy

from uber.config import c


def _current_admin_account(session, admin_account=None):
    if admin_account is not None:
        return admin_account
    from uber.models import AdminAccount
    try:
        # Outside a web request (cron tasks, scripts, tests) cherrypy
        # has no session tool bound and touching cherrypy.session raises
        # AttributeError - callers with no explicit actor get None, the
        # same as an unauthenticated request.
        account_id = cherrypy.session.get('account_id') if cherrypy.session else None
    except AttributeError:
        return None
    if not account_id:
        return None
    return session.query(AdminAccount).get(account_id)


def is_lottery_admin(admin_account=None):
    """True when the current (or given) admin holds the global lottery-admin role.

    Implemented as the existing `hotel_lottery_admin` site-section access so
    that the UI's existing permission UX continues to work. When called with
    no `admin_account`, reads from the current cherrypy request session.
    """
    if admin_account is None:
        return bool(c.HAS_HOTEL_LOTTERY_ADMIN_ACCESS)
    # When an explicit admin is passed, walk their access groups directly so
    # the check is testable without a live cherrypy request. Write access
    # only: read-only section access must not confer edit capabilities
    # (is_lottery_admin short-circuits every can_edit_* check to True).
    return 'hotel_lottery_admin' in admin_account.write_access_set


def _partition_grant(session, admin_account, partition_id):
    if admin_account is None or not partition_id:
        return None
    from uber.models import PartitionOwner
    return (session.query(PartitionOwner)
            .filter_by(admin_account_id=admin_account.id,
                       partition_id=str(partition_id))
            .one_or_none())


def _partition_capability(session, partition_id, flag, *, admin_account=None):
    """Return True if the admin is a lottery admin, or holds the given flag
    via a PartitionOwner row on the given partition."""
    admin = _current_admin_account(session, admin_account)
    if admin is None:
        return False
    if is_lottery_admin(admin):
        return True
    grant = _partition_grant(session, admin, partition_id)
    return bool(grant and getattr(grant, flag, False))


def can_view_inventory_in(session, partition_id, *, admin_account=None):
    return _partition_capability(session, partition_id, 'can_view_inventory',
                                 admin_account=admin_account)


def can_edit_inventory_in(session, partition_id, *, admin_account=None):
    return _partition_capability(session, partition_id, 'can_edit_inventory',
                                 admin_account=admin_account)


def can_view_assignments_in(session, partition_id, *, admin_account=None):
    return _partition_capability(session, partition_id, 'can_view_assignments',
                                 admin_account=admin_account)


def can_edit_assignments_in(session, partition_id, *, admin_account=None):
    return _partition_capability(session, partition_id, 'can_edit_assignments',
                                 admin_account=admin_account)


def can_view_guest_names_in(session, partition_id, *, admin_account=None):
    """Display-name (preferred/known) visibility within a partition."""
    return _partition_capability(session, partition_id, 'can_view_guest_names',
                                 admin_account=admin_account)


def can_view_guest_legal_names(session, partition_id=None, *, admin_account=None):
    """Strongest gate: legal-name visibility, scoped to the given partition.

    Global lottery admins see every attendee's legal name. For everyone
    else, AdminAccount.view_guest_legal_names enables legal-name visibility
    only within partitions the admin actually owns: it requires both the
    account flag and a PartitionOwner grant on the given partition.

    Passing partition_id=None means "no partition context" (aggregate or
    cross-partition views), which only a lottery admin can satisfy.
    """
    admin = _current_admin_account(session, admin_account)
    if admin is None:
        return False
    if is_lottery_admin(admin):
        return True
    if partition_id is None:
        return False
    if not getattr(admin, 'view_guest_legal_names', False):
        return False
    return _partition_grant(session, admin, partition_id) is not None


def has_any_lottery_access(session, admin_account_id):
    """True when the given admin account can reach any hotel-lottery
    admin surface: either as a global lottery admin, or as a partition
    owner with at least one PartitionOwner grant.

    Backs `c.HAS_HOTEL_LOTTERY_ACCESS` (which gates the cross-section
    "Hotel" menu entry) - this is the single definition of "does this
    account have any lottery access at all".
    """
    if not admin_account_id:
        return False
    from uber.models import AdminAccount, PartitionOwner
    account = session.query(AdminAccount).get(admin_account_id)
    if not account:
        return False
    if is_lottery_admin(account):
        return True
    return bool(session.query(PartitionOwner)
                .filter_by(admin_account_id=account.id)
                .first())


def requires_partition_capability(capability, message=None):
    """Decorator gating partition_admin-style handlers on a partition
    capability, replacing the copy-pasted inline checks.

    The partition is resolved from the wrapped handler's own params:
    a `partition_id` argument wins; otherwise `assignment_id` is looked
    up and its RoomAssignment's partition_id is used (redirecting to
    `index?message=Assignment not found.` when the row doesn't exist,
    exactly like the inline blocks did).

    `capability` is either:
      * 'view' - passes when the admin holds can_view_assignments OR
        can_view_inventory on the partition (the old `_gate_view`);
        failure redirects to `index` with "You don't have access to
        that partition."
      * a PartitionOwner flag name (e.g. 'can_edit_assignments');
        failure redirects to the partition's assignments dashboard tab
        with `message` (default: "You don't have permission to edit
        assignments in this partition.").

    Only useful for handlers that redirect on failure - ajax endpoints
    that return JSON keep their own inline gates.
    """
    from uber.errors import HTTPRedirect

    def decorate(fn):
        sig = inspect.signature(fn)

        @functools.wraps(fn)
        def wrapper(self, session, *args, **kwargs):
            bound = sig.bind_partial(self, session, *args, **kwargs)
            partition_id = bound.arguments.get('partition_id')
            if not partition_id:
                assignment_id = bound.arguments.get('assignment_id')
                if assignment_id:
                    from uber.models import RoomAssignment
                    assignment = session.query(RoomAssignment).get(assignment_id)
                    if not assignment:
                        raise HTTPRedirect('index?message={}',
                                           'Assignment not found.')
                    partition_id = assignment.partition_id

            if capability == 'view':
                if not can_view_assignments_in(session, partition_id) and \
                        not can_view_inventory_in(session, partition_id):
                    raise HTTPRedirect(
                        'index?message={}',
                        "You don't have access to that partition.")
            elif not _partition_capability(session, partition_id, capability):
                raise HTTPRedirect(
                    'dashboard?partition_id={}&tab=assignments&message={}',
                    partition_id,
                    message or "You don't have permission to edit "
                               "assignments in this partition.")
            return fn(self, session, *args, **kwargs)
        return wrapper
    return decorate


def record_partition_audit(session, partition_id, action, description='',
                           *, target_type='', target_id=None, admin_account=None):
    """Write one PartitionAuditLog row.

    Lightweight enough to call from every partition-touching admin route.
    Resolves the actor from the cherrypy session unless `admin_account` is
    passed explicitly (for cron / system actions).
    """
    if not partition_id:
        return
    from uber.models import PartitionAuditLog
    if admin_account is None:
        admin_account = _current_admin_account(session)
    entry = PartitionAuditLog(
        partition_id=str(partition_id),
        admin_account_id=admin_account.id if admin_account else None,
        action=action,
        description=description or action,
        target_type=target_type,
        target_id=str(target_id) if target_id else None,
    )
    session.add(entry)
