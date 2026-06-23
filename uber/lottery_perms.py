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

import cherrypy

from uber.config import c


def _current_admin_account(session, admin_account=None):
    if admin_account is not None:
        return admin_account
    from uber.models import AdminAccount
    account_id = cherrypy.session.get('account_id') if cherrypy.session else None
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
    # the check is testable without a live cherrypy request.
    return 'hotel_lottery_admin' in admin_account.write_access_set \
        or 'hotel_lottery_admin' in admin_account.read_access_set


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


def can_send_emails_for(session, partition_id, *, admin_account=None):
    return _partition_capability(session, partition_id, 'can_send_emails',
                                 admin_account=admin_account)


def can_view_guest_names_in(session, partition_id, *, admin_account=None):
    """Display-name (preferred/known) visibility within a partition."""
    return _partition_capability(session, partition_id, 'can_view_guest_names',
                                 admin_account=admin_account)


def can_edit_guest_names_in(session, partition_id, *, admin_account=None):
    return _partition_capability(session, partition_id, 'can_edit_guest_names',
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


def assert_can(check_fn, *args, **kwargs):
    """Raise HTTPRedirect to a 403-style page if check_fn returns False.

    Lightweight gate for admin routes. Call sites can also handle the
    boolean directly; this is provided so common usage stays short.
    """
    if check_fn(*args, **kwargs):
        return
    from uber.errors import HTTPRedirect
    raise HTTPRedirect('../accounts/insufficient_privileges')
