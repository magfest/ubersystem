import uuid

from uber.models import AdminAccount, Attendee, Email, InventoryPartition, PartitionOwner
from uber.site_sections.hotel_lottery_admin import _notify_partition_owners_of_inventory_change


def test_inventory_change_emails_the_partition_owner(session):
    owner = Attendee(first_name='Lorraine', last_name='Baines', email=f'{uuid.uuid4().hex}@example.com')
    admin = AdminAccount(attendee=owner, hashed='')
    partition = InventoryPartition(name=f'Staff Overflow {uuid.uuid4().hex[:6]}')
    session.add_all([owner, admin, partition,
                     PartitionOwner(admin_account=admin, partition=partition, can_view_inventory=True)])
    session.flush()

    _notify_partition_owners_of_inventory_change(session, partition, change_description='Hilton King: 10 to 12')
    session.flush()

    email = session.query(Email).filter(Email.ident == 'hotel_lottery_inventory_changed_owner',
                                        Email.fk_id == owner.id).one()
    assert email.to == owner.email
    assert 'Lorraine' in email.body
    assert partition.name in email.body
    assert f'partition_id={partition.id}' in email.body
    assert 'Hilton King: 10 to 12' in email.body
