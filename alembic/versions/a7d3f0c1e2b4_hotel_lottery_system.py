"""Hotel lottery system.

Creates the hotel-lottery schema: inventory (hotels, room types, partitions,
nightly quantities), lottery runs, per-room assignments and occupants, room
invites, waitlist reveals, partition ownership/permissions, audit logging,
and room-issue notes. Replaces the legacy room/hotel_requests tables and
migrates existing lottery applications onto the new room_assignment model.

Revision ID: a7d3f0c1e2b4
Revises: 4df6bfee2c69
Create Date: 2026-06-10 00:00:00.000000
"""

revision = 'a7d3f0c1e2b4'
down_revision = '4885cb7df802'
branch_labels = None
depends_on = None

from alembic import op
from sqlalchemy.dialects import postgresql
from uber.config import c
import sqlalchemy as sa


LEGACY_COLUMNS = [
    'assigned_check_in_date',
    'assigned_check_out_date',
    'deposit_cutoff_date',
    'hotel_confirmation_number',
    'booking_url',
    'lottery_name',
    'cc_token',
    'cc_last_four',
    'cc_card_type',
    'cc_card_holder',
    'cc_card_expiry',
    'cc_issuer_brand',
    'cc_issuer_bank',
    'cc_issuer_country',
    'cc_issuer_card_type',
    'cc_issuer_card_level',
    'cc_captured_at',
    'address1',
    'address2',
    'city',
    'region',
    'zip_code',
    'country',
]


def upgrade():
    op.create_table('inventory_partition',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('created', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_updated', sa.DateTime(timezone=True), nullable=False),
    sa.Column('external_id', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('last_synced', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('name', sa.Unicode(), nullable=False),
    sa.Column('description', sa.Unicode(), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_inventory_partition'))
    )
    op.create_table('lottery_hotel',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('created', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_updated', sa.DateTime(timezone=True), nullable=False),
    sa.Column('external_id', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('last_synced', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('name', sa.Unicode(), nullable=False),
    sa.Column('export_name', sa.Unicode(), nullable=False),
    sa.Column('description', sa.Unicode(), nullable=False),
    sa.Column('description_right', sa.Unicode(), nullable=False),
    sa.Column('footnote', sa.Unicode(), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_lottery_hotel'))
    )
    op.create_table('lottery_room_type',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('created', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_updated', sa.DateTime(timezone=True), nullable=False),
    sa.Column('external_id', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('last_synced', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('name', sa.Unicode(), nullable=False),
    sa.Column('export_name', sa.Unicode(), nullable=False),
    sa.Column('description', sa.Unicode(), nullable=False),
    sa.Column('description_right', sa.Unicode(), nullable=False),
    sa.Column('footnote', sa.Unicode(), nullable=False),
    sa.Column('capacity', sa.Integer(), nullable=False),
    sa.Column('min_capacity', sa.Integer(), nullable=False),
    sa.Column('is_suite', sa.Boolean(), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_lottery_room_type'))
    )
    op.create_table('lottery_run',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('created', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_updated', sa.DateTime(timezone=True), nullable=False),
    sa.Column('external_id', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('last_synced', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('name', sa.Unicode(), nullable=False),
    sa.Column('status', sa.Integer(), server_default='240058174', nullable=False),
    sa.Column('run_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('awarded_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('reverted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('lottery_group', sa.Unicode(), nullable=False),
    sa.Column('lottery_type', sa.Unicode(), nullable=False),
    sa.Column('cutoff', sa.DateTime(timezone=True), nullable=True),
    sa.Column('hotel_filter', sa.Unicode(), nullable=True),
    sa.Column('room_type_filter', sa.Unicode(), nullable=True),
    sa.Column('inventory_filter', sa.Unicode(), nullable=True),
    sa.Column('partition_filter', sa.Unicode(), nullable=True),
    sa.Column('entries_considered', sa.Integer(), nullable=False),
    sa.Column('rooms_assigned', sa.Integer(), nullable=False),
    sa.Column('rooms_available_before', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_lottery_run'))
    )
    op.create_table('hotel_export_log',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('created', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_updated', sa.DateTime(timezone=True), nullable=False),
    sa.Column('external_id', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('last_synced', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('hotel_id', sa.Uuid(as_uuid=False), nullable=True),
    sa.Column('export_type', sa.Unicode(), nullable=False),
    sa.Column('exported_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('exported_by', sa.Unicode(), nullable=False),
    sa.Column('record_count', sa.Integer(), nullable=False),
    sa.Column('notes', sa.Unicode(), nullable=False),
    sa.ForeignKeyConstraint(['hotel_id'], ['lottery_hotel.id'], name=op.f('fk_hotel_export_log_hotel_id_lottery_hotel')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_hotel_export_log'))
    )
    op.create_table('hotel_room_inventory',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('created', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_updated', sa.DateTime(timezone=True), nullable=False),
    sa.Column('external_id', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('last_synced', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('hotel_id', sa.Uuid(as_uuid=False), nullable=True),
    sa.Column('room_type_id', sa.Uuid(as_uuid=False), nullable=True),
    sa.Column('suite_type_id', sa.Uuid(as_uuid=False), nullable=True),
    sa.Column('quantity', sa.Integer(), nullable=False),
    sa.Column('capacity', sa.Integer(), nullable=False),
    sa.Column('min_capacity', sa.Integer(), nullable=False),
    sa.Column('name', sa.Unicode(), nullable=False),
    sa.Column('is_suite', sa.Boolean(), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('vault_reference', sa.Unicode(), nullable=True),
    sa.Column('info_url', sa.Unicode(), nullable=False),
    sa.Column('price', sa.Unicode(), nullable=False),
    sa.Column('staff_price', sa.Unicode(), nullable=False),
    sa.ForeignKeyConstraint(['hotel_id'], ['lottery_hotel.id'], name=op.f('fk_hotel_room_inventory_hotel_id_lottery_hotel')),
    sa.ForeignKeyConstraint(['room_type_id'], ['lottery_room_type.id'], name=op.f('fk_hotel_room_inventory_room_type_id_lottery_room_type')),
    sa.ForeignKeyConstraint(['suite_type_id'], ['lottery_room_type.id'], name=op.f('fk_hotel_room_inventory_suite_type_id_lottery_room_type')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_hotel_room_inventory'))
    )
    op.create_table('inventory_night_quantity',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('created', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_updated', sa.DateTime(timezone=True), nullable=False),
    sa.Column('external_id', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('last_synced', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('inventory_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('night_date', sa.Date(), nullable=False),
    sa.Column('quantity', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['inventory_id'], ['hotel_room_inventory.id'], name=op.f('fk_inventory_night_quantity_inventory_id_hotel_room_inventory')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_inventory_night_quantity')),
    sa.UniqueConstraint('inventory_id', 'night_date', name='uq_inventory_night')
    )
    op.create_table('inventory_partition_block',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('created', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_updated', sa.DateTime(timezone=True), nullable=False),
    sa.Column('external_id', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('last_synced', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('partition_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('inventory_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('quantity', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['inventory_id'], ['hotel_room_inventory.id'], name=op.f('fk_inventory_partition_block_inventory_id_hotel_room_inventory')),
    sa.ForeignKeyConstraint(['partition_id'], ['inventory_partition.id'], name=op.f('fk_inventory_partition_block_partition_id_inventory_partition')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_inventory_partition_block')),
    sa.UniqueConstraint('partition_id', 'inventory_id', name='uq_partition_inventory')
    )
    op.add_column('lottery_application', sa.Column('assigned_inventory_id', sa.Uuid(as_uuid=False), nullable=True))
    op.add_column('lottery_application', sa.Column('partition_id', sa.Uuid(as_uuid=False), nullable=True))
    op.add_column('lottery_application', sa.Column('export_locked', sa.Boolean(), nullable=False))
    op.add_column('lottery_application', sa.Column('invite_token', sa.Unicode(), nullable=False))
    op.add_column('lottery_application', sa.Column('invited_by_id', sa.Uuid(as_uuid=False), nullable=True))
    op.add_column('lottery_application', sa.Column('invite_status', sa.Integer(), server_default='117453886', nullable=False))
    op.add_column('lottery_application', sa.Column('invite_expires_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('lottery_application', sa.Column('cc_token', sa.Unicode(), nullable=True))
    op.add_column('lottery_application', sa.Column('cc_last_four', sa.Unicode(), nullable=True))
    op.add_column('lottery_application', sa.Column('cc_card_type', sa.Unicode(), nullable=True))
    op.add_column('lottery_application', sa.Column('cc_card_holder', sa.Unicode(), nullable=True))
    op.add_column('lottery_application', sa.Column('cc_card_expiry', sa.Unicode(), nullable=True))
    op.add_column('lottery_application', sa.Column('cc_issuer_brand', sa.Unicode(), nullable=True))
    op.add_column('lottery_application', sa.Column('cc_issuer_bank', sa.Unicode(), nullable=True))
    op.add_column('lottery_application', sa.Column('cc_issuer_country', sa.Unicode(), nullable=True))
    op.add_column('lottery_application', sa.Column('cc_issuer_card_type', sa.Unicode(), nullable=True))
    op.add_column('lottery_application', sa.Column('cc_issuer_card_level', sa.Unicode(), nullable=True))
    op.add_column('lottery_application', sa.Column('cc_captured_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('lottery_application', sa.Column('address1', sa.Unicode(), nullable=False))
    op.add_column('lottery_application', sa.Column('address2', sa.Unicode(), nullable=False))
    op.add_column('lottery_application', sa.Column('city', sa.Unicode(), nullable=False))
    op.add_column('lottery_application', sa.Column('region', sa.Unicode(), nullable=False))
    op.add_column('lottery_application', sa.Column('zip_code', sa.Unicode(), nullable=False))
    op.add_column('lottery_application', sa.Column('country', sa.Unicode(), nullable=False))
    op.add_column('lottery_application', sa.Column('hotel_confirmation_number', sa.Unicode(), nullable=True))
    op.add_column('lottery_application', sa.Column('special_requests', sa.Unicode(), nullable=False))
    op.add_column('lottery_application', sa.Column('hotel_rewards_number', sa.Unicode(), nullable=False))
    op.add_column('lottery_application', sa.Column('last_modified_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('lottery_application', sa.Column('lottery_run_id', sa.Uuid(as_uuid=False), nullable=True))
    op.create_foreign_key(op.f('fk_lottery_application_invited_by_id_lottery_application'), 'lottery_application', 'lottery_application', ['invited_by_id'], ['id'])
    op.create_foreign_key(op.f('fk_lottery_application_assigned_inventory_id_hotel_room_inventory'), 'lottery_application', 'hotel_room_inventory', ['assigned_inventory_id'], ['id'])
    op.create_foreign_key(op.f('fk_lottery_application_lottery_run_id_lottery_run'), 'lottery_application', 'lottery_run', ['lottery_run_id'], ['id'])
    op.create_foreign_key(op.f('fk_lottery_application_partition_id_inventory_partition'), 'lottery_application', 'inventory_partition', ['partition_id'], ['id'])
    op.drop_column('lottery_application', 'final_status_hidden')
    op.drop_column('lottery_application', 'booking_url_hidden')
    op.drop_column('lottery_application', 'assigned_room_type')
    op.drop_column('lottery_application', 'assigned_suite_type')
    op.drop_column('lottery_application', 'assigned_hotel')

    op.drop_table('room_assignment')
    op.drop_table('hotel_requests')
    op.drop_table('room')

    with op.batch_alter_table('attendee') as batch_op:
        batch_op.drop_column('hotel_pin')

    op.create_table(
        'room_assignment',
        sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
        sa.Column('created', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_updated', sa.DateTime(timezone=True), nullable=False),
        sa.Column('external_id', postgresql.JSONB(astext_type=sa.Text()),
                  server_default='{}', nullable=False),
        sa.Column('last_synced', postgresql.JSONB(astext_type=sa.Text()),
                  server_default='{}', nullable=False),

        sa.Column('attendee_id', sa.Uuid(as_uuid=False), nullable=False),
        sa.Column('inventory_id', sa.Uuid(as_uuid=False), nullable=True),
        sa.Column('lottery_application_id', sa.Uuid(as_uuid=False), nullable=True),
        sa.Column('lottery_run_id', sa.Uuid(as_uuid=False), nullable=True),
        sa.Column('parent_assignment_id', sa.Uuid(as_uuid=False), nullable=True),
        sa.Column('partition_id', sa.Uuid(as_uuid=False), nullable=True),

        sa.Column('assignment_reason', sa.Integer(),
                  server_default=str(c.MANUAL), nullable=False),
        sa.Column('status', sa.Integer(),
                  server_default=str(c.ASSIGNED), nullable=False),
        sa.Column('require_cc', sa.Boolean(),
                  server_default=sa.text('true'), nullable=False),

        sa.Column('assigned_check_in_date', sa.Date(), nullable=True),
        sa.Column('assigned_check_out_date', sa.Date(), nullable=True),
        sa.Column('deposit_cutoff_date', sa.Date(), nullable=True),

        sa.Column('booking_url', sa.Unicode(), server_default='', nullable=False),
        sa.Column('hotel_confirmation_number', sa.Unicode(), nullable=True),
        sa.Column('cancellation_confirmation_number', sa.Unicode(), nullable=True),
        sa.Column('special_requests', sa.Unicode(), server_default='', nullable=False),
        sa.Column('hotel_rewards_number', sa.Unicode(), server_default='', nullable=False),

        sa.Column('cc_token', sa.Unicode(), nullable=True),
        sa.Column('cc_last_four', sa.Unicode(), nullable=True),
        sa.Column('cc_card_type', sa.Unicode(), nullable=True),
        sa.Column('cc_card_holder', sa.Unicode(), nullable=True),
        sa.Column('cc_card_expiry', sa.Unicode(), nullable=True),
        sa.Column('cc_issuer_brand', sa.Unicode(), nullable=True),
        sa.Column('cc_issuer_bank', sa.Unicode(), nullable=True),
        sa.Column('cc_issuer_country', sa.Unicode(), nullable=True),
        sa.Column('cc_issuer_card_type', sa.Unicode(), nullable=True),
        sa.Column('cc_issuer_card_level', sa.Unicode(), nullable=True),
        sa.Column('cc_captured_at', sa.DateTime(timezone=True), nullable=True),

        sa.Column('address1', sa.Unicode(), server_default='', nullable=False),
        sa.Column('address2', sa.Unicode(), server_default='', nullable=False),
        sa.Column('city', sa.Unicode(), server_default='', nullable=False),
        sa.Column('region', sa.Unicode(), server_default='', nullable=False),
        sa.Column('zip_code', sa.Unicode(), server_default='', nullable=False),
        sa.Column('country', sa.Unicode(), server_default='', nullable=False),

        sa.Column('last_modified_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_confirmed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('admin_notes', sa.Unicode(), server_default='', nullable=False),

        sa.ForeignKeyConstraint(['attendee_id'], ['attendee.id'],
                                name=op.f('fk_room_assignment_attendee_id_attendee'),
                                ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['inventory_id'], ['hotel_room_inventory.id'],
                                name=op.f('fk_room_assignment_inventory_id_hotel_room_inventory')),
        sa.ForeignKeyConstraint(['lottery_application_id'], ['lottery_application.id'],
                                name=op.f('fk_room_assignment_lottery_application_id_lottery_application')),
        sa.ForeignKeyConstraint(['lottery_run_id'], ['lottery_run.id'],
                                name=op.f('fk_room_assignment_lottery_run_id_lottery_run')),
        sa.ForeignKeyConstraint(['parent_assignment_id'], ['room_assignment.id'],
                                name=op.f('fk_room_assignment_parent_assignment_id_room_assignment')),
        sa.ForeignKeyConstraint(['partition_id'], ['inventory_partition.id'],
                                name=op.f('fk_room_assignment_partition_id_inventory_partition')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_room_assignment')),
    )

    op.create_index(op.f('ix_room_assignment_attendee_id'),
                    'room_assignment', ['attendee_id'], unique=False)
    op.create_index(op.f('ix_room_assignment_inventory_id'),
                    'room_assignment', ['inventory_id'], unique=False)
    op.create_index(op.f('ix_room_assignment_lottery_application_id'),
                    'room_assignment', ['lottery_application_id'], unique=False)
    op.create_index(op.f('ix_room_assignment_partition_id'),
                    'room_assignment', ['partition_id'], unique=False)
    op.create_index(op.f('ix_room_assignment_status'),
                    'room_assignment', ['status'], unique=False)

    # Backfill: one RoomAssignment per LotteryApplication that has an inventory
    # assignment. Applications with status SECURED or CANCELLED carry that
    # status across; everything else (AWARDED, PROCESSED, etc.) becomes
    # ASSIGNED on the room_assignment row.
    op.execute(sa.text(f"""
        INSERT INTO room_assignment (
            id, created, last_updated, external_id, last_synced,
            attendee_id, inventory_id, lottery_application_id, lottery_run_id,
            partition_id,
            assignment_reason, status, require_cc,
            assigned_check_in_date, assigned_check_out_date, deposit_cutoff_date,
            booking_url, hotel_confirmation_number,
            special_requests, hotel_rewards_number,
            cc_token, cc_last_four, cc_card_type, cc_card_holder, cc_card_expiry,
            cc_issuer_brand, cc_issuer_bank, cc_issuer_country,
            cc_issuer_card_type, cc_issuer_card_level, cc_captured_at,
            address1, address2, city, region, zip_code, country,
            last_modified_at, admin_notes
        )
        SELECT
            gen_random_uuid(),
            timezone('utc', now()), timezone('utc', now()),
            '{{}}'::jsonb, '{{}}'::jsonb,
            attendee_id, assigned_inventory_id, id, lottery_run_id,
            partition_id,
            {c.MIGRATED},
            CASE
                WHEN status = {c.SECURED} THEN {c.SECURED}
                WHEN status = {c.CANCELLED} THEN {c.CANCELLED}
                ELSE {c.ASSIGNED}
            END,
            true,
            assigned_check_in_date, assigned_check_out_date, deposit_cutoff_date,
            COALESCE(booking_url, ''), hotel_confirmation_number,
            COALESCE(special_requests, ''), COALESCE(hotel_rewards_number, ''),
            cc_token, cc_last_four, cc_card_type, cc_card_holder, cc_card_expiry,
            cc_issuer_brand, cc_issuer_bank, cc_issuer_country,
            cc_issuer_card_type, cc_issuer_card_level, cc_captured_at,
            COALESCE(address1, ''), COALESCE(address2, ''), COALESCE(city, ''),
            COALESCE(region, ''), COALESCE(zip_code, ''), COALESCE(country, ''),
            last_modified_at, ''
        FROM lottery_application
        WHERE assigned_inventory_id IS NOT NULL
          AND attendee_id IS NOT NULL
    """))

    with op.batch_alter_table('lottery_run') as batch_op:
        batch_op.add_column(sa.Column('card_deadline', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('apply_cutoff', sa.Boolean(),
                                      server_default=sa.text('true'), nullable=False))
        batch_op.add_column(sa.Column('confirmation_window_start',
                                      sa.DateTime(timezone=True), nullable=True))

    with op.batch_alter_table('lottery_application') as batch_op:
        batch_op.add_column(sa.Column('confirmation_requested_at',
                                      sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('last_confirmed_at',
                                      sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        'partition_owner',
        sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
        sa.Column('created', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_updated', sa.DateTime(timezone=True), nullable=False),
        sa.Column('external_id', postgresql.JSONB(astext_type=sa.Text()),
                  server_default='{}', nullable=False),
        sa.Column('last_synced', postgresql.JSONB(astext_type=sa.Text()),
                  server_default='{}', nullable=False),

        sa.Column('admin_account_id', sa.Uuid(as_uuid=False), nullable=False),
        sa.Column('partition_id', sa.Uuid(as_uuid=False), nullable=False),

        sa.Column('can_view_inventory', sa.Boolean(),
                  server_default=sa.text('true'), nullable=False),
        sa.Column('can_edit_inventory', sa.Boolean(),
                  server_default=sa.text('false'), nullable=False),
        sa.Column('can_view_assignments', sa.Boolean(),
                  server_default=sa.text('true'), nullable=False),
        sa.Column('can_edit_assignments', sa.Boolean(),
                  server_default=sa.text('false'), nullable=False),
        sa.Column('can_view_guest_names', sa.Boolean(),
                  server_default=sa.text('false'), nullable=False),
        sa.Column('can_edit_guest_names', sa.Boolean(),
                  server_default=sa.text('false'), nullable=False),
        sa.Column('can_send_emails', sa.Boolean(),
                  server_default=sa.text('false'), nullable=False),

        sa.ForeignKeyConstraint(['admin_account_id'], ['admin_account.id'],
                                name=op.f('fk_partition_owner_admin_account_id_admin_account'),
                                ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['partition_id'], ['inventory_partition.id'],
                                name=op.f('fk_partition_owner_partition_id_inventory_partition'),
                                ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_partition_owner')),
        sa.UniqueConstraint('admin_account_id', 'partition_id',
                            name='uq_partition_owner_admin_partition'),
    )

    op.create_index(op.f('ix_partition_owner_admin_account_id'),
                    'partition_owner', ['admin_account_id'], unique=False)
    op.create_index(op.f('ix_partition_owner_partition_id'),
                    'partition_owner', ['partition_id'], unique=False)

    with op.batch_alter_table('admin_account') as batch_op:
        batch_op.add_column(sa.Column('view_guest_legal_names', sa.Boolean(),
                                      server_default=sa.text('false'), nullable=False))

    op.create_table(
        'night_shift_requirement',
        sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
        sa.Column('created', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_updated', sa.DateTime(timezone=True), nullable=False),
        sa.Column('external_id', postgresql.JSONB(astext_type=sa.Text()),
                  server_default='{}', nullable=False),
        sa.Column('last_synced', postgresql.JSONB(astext_type=sa.Text()),
                  server_default='{}', nullable=False),

        sa.Column('night_date', sa.Date(), nullable=False),
        sa.Column('kind', sa.Integer(),
                  server_default=str(c.NONE), nullable=False),
        sa.Column('shift_window_start', sa.DateTime(timezone=True), nullable=True),
        sa.Column('shift_window_end', sa.DateTime(timezone=True), nullable=True),
        sa.Column('required_weighted_hours', sa.Integer(),
                  server_default='0', nullable=False),

        sa.PrimaryKeyConstraint('id', name=op.f('pk_night_shift_requirement')),
        sa.UniqueConstraint('night_date', name='uq_night_shift_requirement_date'),
    )

    op.create_table(
        'waitlist_reveal',
        sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
        sa.Column('created', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_updated', sa.DateTime(timezone=True), nullable=False),
        sa.Column('external_id', postgresql.JSONB(astext_type=sa.Text()),
                  server_default='{}', nullable=False),
        sa.Column('last_synced', postgresql.JSONB(astext_type=sa.Text()),
                  server_default='{}', nullable=False),

        sa.Column('name', sa.Unicode(), server_default='', nullable=False),
        sa.Column('external_url', sa.Unicode(), server_default='', nullable=False),
        sa.Column('reveal_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('audience_description', sa.Unicode(), server_default='', nullable=False),
        sa.Column('active', sa.Boolean(),
                  server_default=sa.text('true'), nullable=False),

        sa.PrimaryKeyConstraint('id', name=op.f('pk_waitlist_reveal')),
    )

    op.create_table(
        'waitlist_reveal_link',
        sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
        sa.Column('created', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_updated', sa.DateTime(timezone=True), nullable=False),
        sa.Column('external_id', postgresql.JSONB(astext_type=sa.Text()),
                  server_default='{}', nullable=False),
        sa.Column('last_synced', postgresql.JSONB(astext_type=sa.Text()),
                  server_default='{}', nullable=False),

        sa.Column('waitlist_reveal_id', sa.Uuid(as_uuid=False), nullable=False),
        sa.Column('attendee_id', sa.Uuid(as_uuid=False), nullable=False),
        sa.Column('token', sa.Unicode(), nullable=False),
        sa.Column('emailed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('clicked_at', sa.DateTime(timezone=True), nullable=True),

        sa.ForeignKeyConstraint(['waitlist_reveal_id'], ['waitlist_reveal.id'],
                                name=op.f('fk_waitlist_reveal_link_waitlist_reveal_id_waitlist_reveal'),
                                ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['attendee_id'], ['attendee.id'],
                                name=op.f('fk_waitlist_reveal_link_attendee_id_attendee'),
                                ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_waitlist_reveal_link')),
        sa.UniqueConstraint('waitlist_reveal_id', 'attendee_id',
                            name='uq_waitlist_reveal_attendee'),
        sa.UniqueConstraint('token', name='uq_waitlist_reveal_link_token'),
    )

    op.create_index(op.f('ix_waitlist_reveal_link_attendee_id'),
                    'waitlist_reveal_link', ['attendee_id'], unique=False)
    op.create_index(op.f('ix_waitlist_reveal_link_waitlist_reveal_id'),
                    'waitlist_reveal_link', ['waitlist_reveal_id'], unique=False)

    op.create_table(
        'partition_audit_log',
        sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
        sa.Column('created', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_updated', sa.DateTime(timezone=True), nullable=False),
        sa.Column('external_id', postgresql.JSONB(astext_type=sa.Text()),
                  server_default='{}', nullable=False),
        sa.Column('last_synced', postgresql.JSONB(astext_type=sa.Text()),
                  server_default='{}', nullable=False),

        sa.Column('partition_id', sa.Uuid(as_uuid=False), nullable=False),
        sa.Column('admin_account_id', sa.Uuid(as_uuid=False), nullable=True),
        sa.Column('when', sa.DateTime(timezone=True), nullable=False),
        sa.Column('action', sa.Unicode(), server_default='', nullable=False),
        sa.Column('description', sa.Unicode(), server_default='', nullable=False),
        sa.Column('target_type', sa.Unicode(), server_default='', nullable=False),
        sa.Column('target_id', sa.Uuid(as_uuid=False), nullable=True),

        sa.ForeignKeyConstraint(['partition_id'], ['inventory_partition.id'],
                                name=op.f('fk_partition_audit_log_partition_id_inventory_partition'),
                                ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['admin_account_id'], ['admin_account.id'],
                                name=op.f('fk_partition_audit_log_admin_account_id_admin_account'),
                                ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_partition_audit_log')),
    )

    op.create_index(op.f('ix_partition_audit_log_partition_id'),
                    'partition_audit_log', ['partition_id'], unique=False)
    op.create_index(op.f('ix_partition_audit_log_when'),
                    'partition_audit_log', ['when'], unique=False)

    with op.batch_alter_table('lottery_room_type') as batch_op:
        batch_op.add_column(sa.Column(
            'connects_to_type_id', sa.Uuid(as_uuid=False), nullable=True))
        batch_op.add_column(sa.Column(
            'connector_quantity', sa.Integer(),
            server_default='0', nullable=False))
        batch_op.create_foreign_key(
            op.f('fk_lottery_room_type_connects_to_type_id_lottery_room_type'),
            'lottery_room_type', ['connects_to_type_id'], ['id'])

    op.create_index(op.f('ix_lottery_room_type_connects_to_type_id'),
                    'lottery_room_type', ['connects_to_type_id'], unique=False)

    # The FK on assigned_inventory_id needs to be dropped before the column.
    with op.batch_alter_table('lottery_application') as batch_op:
        batch_op.drop_constraint(
            op.f('fk_lottery_application_assigned_inventory_id_hotel_room_inventory'),
            type_='foreignkey')
        batch_op.drop_column('assigned_inventory_id')
        for col in LEGACY_COLUMNS:
            batch_op.drop_column(col)

    op.create_table(
        'room_assignment_occupant',
        sa.Column('room_assignment_id', sa.Uuid(as_uuid=False), nullable=False),
        sa.Column('attendee_id', sa.Uuid(as_uuid=False), nullable=False),
        sa.ForeignKeyConstraint(['attendee_id'], ['attendee.id'],
                                name=op.f('fk_room_assignment_occupant_attendee_id_attendee'),
                                ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['room_assignment_id'], ['room_assignment.id'],
                                name=op.f('fk_room_assignment_occupant_room_assignment_id_room_assignment'),
                                ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('room_assignment_id', 'attendee_id',
                                name=op.f('pk_room_assignment_occupant')),
    )

    op.create_index(op.f('ix_room_assignment_occupant_attendee_id'),
                    'room_assignment_occupant', ['attendee_id'], unique=False)

    # Attendee hotel-name overrides, used in place of the lottery
    # application's legal-name columns.
    op.add_column(
        'attendee',
        sa.Column('hotel_first_name', sa.Unicode(),
                  server_default='', nullable=False))
    op.add_column(
        'attendee',
        sa.Column('hotel_last_name', sa.Unicode(),
                  server_default='', nullable=False))

    op.drop_column('lottery_application', 'legal_first_name')
    op.drop_column('lottery_application', 'legal_last_name')

    # Per-room invite table. Includes the full MagModel column set
    # (id/created/last_updated/external_id/last_synced) so generated
    # queries resolve against existing columns.
    op.create_table(
        'room_assignment_invite',
        sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
        sa.Column('created', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_updated', sa.DateTime(timezone=True), nullable=False),
        sa.Column('external_id', postgresql.JSONB(astext_type=sa.Text()),
                  server_default='{}', nullable=False),
        sa.Column('last_synced', postgresql.JSONB(astext_type=sa.Text()),
                  server_default='{}', nullable=False),

        sa.Column('room_assignment_id', sa.Uuid(as_uuid=False), nullable=False),
        sa.Column('invite_token', sa.Unicode(), server_default='', nullable=False),
        sa.Column('email', sa.Unicode(), server_default='', nullable=False),

        sa.ForeignKeyConstraint(
            ['room_assignment_id'], ['room_assignment.id'],
            name=op.f('fk_room_assignment_invite_room_assignment_id_room_assignment'),
            ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_room_assignment_invite')),
        sa.UniqueConstraint('invite_token',
                            name='uq_room_assignment_invite_token'),
    )
    op.create_index(
        op.f('ix_room_assignment_invite_room_assignment_id'),
        'room_assignment_invite', ['room_assignment_id'], unique=False)

    op.add_column(
        'room_assignment',
        sa.Column('waitlisted_check_in_date', sa.Date(), nullable=True))
    op.add_column(
        'room_assignment',
        sa.Column('waitlisted_check_out_date', sa.Date(), nullable=True))

    # Backfill from the owning lottery_application's preferred range, but
    # only where there is actually unfulfilled demand - i.e. the app's
    # range strictly extends the assigned range on at least one end.
    # Skipping rows with no demand keeps the new columns sparse (most
    # rows stay NULL) and avoids dragging app-level requested dates onto
    # rooms whose attendees never wanted a wider window.
    op.execute("""
        UPDATE room_assignment ra
        SET waitlisted_check_in_date = la.earliest_checkin_date,
            waitlisted_check_out_date = la.latest_checkout_date
        FROM lottery_application la
        WHERE ra.lottery_application_id = la.id
          AND ra.assigned_check_in_date IS NOT NULL
          AND ra.assigned_check_out_date IS NOT NULL
          AND la.earliest_checkin_date IS NOT NULL
          AND la.latest_checkout_date IS NOT NULL
          AND (la.earliest_checkin_date < ra.assigned_check_in_date
               OR la.latest_checkout_date > ra.assigned_check_out_date)
    """)

    op.add_column(
        'room_assignment',
        sa.Column('waitlist_started_at', sa.DateTime(timezone=True),
                  nullable=True))

    # Backfill from `created` for any row currently on the waitlist.
    # Rows with no waitlist demand stay at NULL.
    op.execute("""
        UPDATE room_assignment
        SET waitlist_started_at = created
        WHERE waitlist_started_at IS NULL
          AND (waitlisted_check_in_date IS NOT NULL
               OR waitlisted_check_out_date IS NOT NULL)
    """)

    op.create_table(
        'hotel_room_issue_note',
        sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
        sa.Column('created', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_updated', sa.DateTime(timezone=True), nullable=False),
        sa.Column('external_id', postgresql.JSONB(astext_type=sa.Text()),
                  server_default='{}', nullable=False),
        sa.Column('last_synced', postgresql.JSONB(astext_type=sa.Text()),
                  server_default='{}', nullable=False),

        sa.Column('issue_kind', sa.Unicode(), server_default='', nullable=False),
        sa.Column('target_type', sa.Unicode(), server_default='', nullable=False),
        sa.Column('target_id', sa.Unicode(), server_default='', nullable=False),
        sa.Column('hidden', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('admin_notes', sa.Unicode(), server_default='', nullable=False),
        sa.Column('admin_account_id', sa.Uuid(as_uuid=False), nullable=True),

        sa.ForeignKeyConstraint(
            ['admin_account_id'], ['admin_account.id'],
            name=op.f('fk_hotel_room_issue_note_admin_account_id_admin_account'),
            ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_hotel_room_issue_note')),
        sa.UniqueConstraint('issue_kind', 'target_type', 'target_id',
                            name='uq_hotel_room_issue_note'),
    )


def downgrade():
    op.drop_table('hotel_room_issue_note')

    op.drop_column('room_assignment', 'waitlist_started_at')

    op.drop_column('room_assignment', 'waitlisted_check_out_date')
    op.drop_column('room_assignment', 'waitlisted_check_in_date')

    op.drop_index(op.f('ix_room_assignment_invite_room_assignment_id'),
                  table_name='room_assignment_invite')
    op.drop_table('room_assignment_invite')

    op.add_column(
        'lottery_application',
        sa.Column('legal_last_name', sa.Unicode(),
                  server_default='', nullable=False))
    op.add_column(
        'lottery_application',
        sa.Column('legal_first_name', sa.Unicode(),
                  server_default='', nullable=False))

    op.drop_column('attendee', 'hotel_last_name')
    op.drop_column('attendee', 'hotel_first_name')

    op.drop_index(op.f('ix_room_assignment_occupant_attendee_id'),
                  table_name='room_assignment_occupant')
    op.drop_table('room_assignment_occupant')

    with op.batch_alter_table('lottery_application') as batch_op:
        batch_op.add_column(sa.Column('country', sa.Unicode(),
                                      server_default='', nullable=False))
        batch_op.add_column(sa.Column('zip_code', sa.Unicode(),
                                      server_default='', nullable=False))
        batch_op.add_column(sa.Column('region', sa.Unicode(),
                                      server_default='', nullable=False))
        batch_op.add_column(sa.Column('city', sa.Unicode(),
                                      server_default='', nullable=False))
        batch_op.add_column(sa.Column('address2', sa.Unicode(),
                                      server_default='', nullable=False))
        batch_op.add_column(sa.Column('address1', sa.Unicode(),
                                      server_default='', nullable=False))
        batch_op.add_column(sa.Column('cc_captured_at',
                                      sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('cc_issuer_card_level', sa.Unicode(), nullable=True))
        batch_op.add_column(sa.Column('cc_issuer_card_type', sa.Unicode(), nullable=True))
        batch_op.add_column(sa.Column('cc_issuer_country', sa.Unicode(), nullable=True))
        batch_op.add_column(sa.Column('cc_issuer_bank', sa.Unicode(), nullable=True))
        batch_op.add_column(sa.Column('cc_issuer_brand', sa.Unicode(), nullable=True))
        batch_op.add_column(sa.Column('cc_card_expiry', sa.Unicode(), nullable=True))
        batch_op.add_column(sa.Column('cc_card_holder', sa.Unicode(), nullable=True))
        batch_op.add_column(sa.Column('cc_card_type', sa.Unicode(), nullable=True))
        batch_op.add_column(sa.Column('cc_last_four', sa.Unicode(), nullable=True))
        batch_op.add_column(sa.Column('cc_token', sa.Unicode(), nullable=True))
        batch_op.add_column(sa.Column('lottery_name', sa.Unicode(),
                                      server_default='', nullable=False))
        batch_op.add_column(sa.Column('booking_url', sa.Unicode(),
                                      server_default='', nullable=False))
        batch_op.add_column(sa.Column('hotel_confirmation_number', sa.Unicode(), nullable=True))
        batch_op.add_column(sa.Column('deposit_cutoff_date', sa.Date(), nullable=True))
        batch_op.add_column(sa.Column('assigned_check_out_date', sa.Date(), nullable=True))
        batch_op.add_column(sa.Column('assigned_check_in_date', sa.Date(), nullable=True))
        batch_op.add_column(sa.Column('assigned_inventory_id', sa.Uuid(as_uuid=False), nullable=True))
        batch_op.create_foreign_key(
            op.f('fk_lottery_application_assigned_inventory_id_hotel_room_inventory'),
            'hotel_room_inventory', ['assigned_inventory_id'], ['id'])

    op.drop_index(op.f('ix_lottery_room_type_connects_to_type_id'),
                  table_name='lottery_room_type')
    with op.batch_alter_table('lottery_room_type') as batch_op:
        batch_op.drop_constraint(
            op.f('fk_lottery_room_type_connects_to_type_id_lottery_room_type'),
            type_='foreignkey')
        batch_op.drop_column('connector_quantity')
        batch_op.drop_column('connects_to_type_id')

    op.drop_index(op.f('ix_partition_audit_log_when'), table_name='partition_audit_log')
    op.drop_index(op.f('ix_partition_audit_log_partition_id'), table_name='partition_audit_log')
    op.drop_table('partition_audit_log')

    op.drop_index(op.f('ix_waitlist_reveal_link_waitlist_reveal_id'),
                  table_name='waitlist_reveal_link')
    op.drop_index(op.f('ix_waitlist_reveal_link_attendee_id'),
                  table_name='waitlist_reveal_link')
    op.drop_table('waitlist_reveal_link')
    op.drop_table('waitlist_reveal')

    op.drop_table('night_shift_requirement')

    with op.batch_alter_table('admin_account') as batch_op:
        batch_op.drop_column('view_guest_legal_names')

    op.drop_index(op.f('ix_partition_owner_partition_id'), table_name='partition_owner')
    op.drop_index(op.f('ix_partition_owner_admin_account_id'), table_name='partition_owner')
    op.drop_table('partition_owner')

    with op.batch_alter_table('lottery_application') as batch_op:
        batch_op.drop_column('last_confirmed_at')
        batch_op.drop_column('confirmation_requested_at')

    with op.batch_alter_table('lottery_run') as batch_op:
        batch_op.drop_column('confirmation_window_start')
        batch_op.drop_column('apply_cutoff')
        batch_op.drop_column('card_deadline')

    op.drop_index(op.f('ix_room_assignment_status'), table_name='room_assignment')
    op.drop_index(op.f('ix_room_assignment_partition_id'), table_name='room_assignment')
    op.drop_index(op.f('ix_room_assignment_lottery_application_id'), table_name='room_assignment')
    op.drop_index(op.f('ix_room_assignment_inventory_id'), table_name='room_assignment')
    op.drop_index(op.f('ix_room_assignment_attendee_id'), table_name='room_assignment')
    op.drop_table('room_assignment')

    op.create_table(
        'room',
        sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
        sa.Column('created', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_updated', sa.DateTime(timezone=True), nullable=False),
        sa.Column('notes', sa.Unicode(), server_default='', nullable=False),
        sa.Column('message', sa.Unicode(), server_default='', nullable=False),
        sa.Column('locked_in', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('nights', sa.Unicode(), server_default='', nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'hotel_requests',
        sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
        sa.Column('created', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_updated', sa.DateTime(timezone=True), nullable=False),
        sa.Column('attendee_id', sa.Uuid(as_uuid=False), nullable=True),
        sa.Column('nights', sa.Unicode(), server_default='', nullable=False),
        sa.Column('wanted_roommates', sa.Unicode(), server_default='', nullable=False),
        sa.Column('unwanted_roommates', sa.Unicode(), server_default='', nullable=False),
        sa.Column('special_needs', sa.Unicode(), server_default='', nullable=False),
        sa.Column('approved', sa.Boolean(), server_default='false', nullable=False),
        sa.ForeignKeyConstraint(['attendee_id'], ['attendee.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('attendee_id'),
    )

    op.create_table(
        'room_assignment',
        sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
        sa.Column('created', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_updated', sa.DateTime(timezone=True), nullable=False),
        sa.Column('room_id', sa.Uuid(as_uuid=False), nullable=True),
        sa.Column('attendee_id', sa.Uuid(as_uuid=False), nullable=True),
        sa.ForeignKeyConstraint(['attendee_id'], ['attendee.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['room_id'], ['room.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )

    with op.batch_alter_table('attendee') as batch_op:
        batch_op.add_column(sa.Column('hotel_pin', sa.Unicode(), nullable=True))
        batch_op.create_unique_constraint('uq_attendee_hotel_pin', ['hotel_pin'])

    op.add_column('lottery_application', sa.Column('assigned_hotel', sa.INTEGER(), autoincrement=False, nullable=True))
    op.add_column('lottery_application', sa.Column('assigned_suite_type', sa.INTEGER(), autoincrement=False, nullable=True))
    op.add_column('lottery_application', sa.Column('assigned_room_type', sa.INTEGER(), autoincrement=False, nullable=True))
    op.add_column('lottery_application', sa.Column('booking_url_hidden', sa.BOOLEAN(), server_default=sa.text('true'), autoincrement=False, nullable=False))
    op.add_column('lottery_application', sa.Column('final_status_hidden', sa.BOOLEAN(), server_default=sa.text('true'), autoincrement=False, nullable=False))
    op.drop_constraint(op.f('fk_lottery_application_partition_id_inventory_partition'), 'lottery_application', type_='foreignkey')
    op.drop_constraint(op.f('fk_lottery_application_lottery_run_id_lottery_run'), 'lottery_application', type_='foreignkey')
    op.drop_constraint(op.f('fk_lottery_application_assigned_inventory_id_hotel_room_inventory'), 'lottery_application', type_='foreignkey')
    op.drop_constraint(op.f('fk_lottery_application_invited_by_id_lottery_application'), 'lottery_application', type_='foreignkey')
    op.drop_column('lottery_application', 'lottery_run_id')
    op.drop_column('lottery_application', 'last_modified_at')
    op.drop_column('lottery_application', 'hotel_rewards_number')
    op.drop_column('lottery_application', 'special_requests')
    op.drop_column('lottery_application', 'hotel_confirmation_number')
    op.drop_column('lottery_application', 'country')
    op.drop_column('lottery_application', 'zip_code')
    op.drop_column('lottery_application', 'region')
    op.drop_column('lottery_application', 'city')
    op.drop_column('lottery_application', 'address2')
    op.drop_column('lottery_application', 'address1')
    op.drop_column('lottery_application', 'cc_captured_at')
    op.drop_column('lottery_application', 'cc_issuer_card_level')
    op.drop_column('lottery_application', 'cc_issuer_card_type')
    op.drop_column('lottery_application', 'cc_issuer_country')
    op.drop_column('lottery_application', 'cc_issuer_bank')
    op.drop_column('lottery_application', 'cc_issuer_brand')
    op.drop_column('lottery_application', 'cc_card_expiry')
    op.drop_column('lottery_application', 'cc_card_holder')
    op.drop_column('lottery_application', 'cc_card_type')
    op.drop_column('lottery_application', 'cc_last_four')
    op.drop_column('lottery_application', 'cc_token')
    op.drop_column('lottery_application', 'invite_expires_at')
    op.drop_column('lottery_application', 'invite_status')
    op.drop_column('lottery_application', 'invited_by_id')
    op.drop_column('lottery_application', 'invite_token')
    op.drop_column('lottery_application', 'export_locked')
    op.drop_column('lottery_application', 'partition_id')
    op.drop_column('lottery_application', 'assigned_inventory_id')
    op.drop_table('inventory_partition_block')
    op.drop_table('inventory_night_quantity')
    op.drop_table('hotel_room_inventory')
    op.drop_table('hotel_export_log')
    op.drop_table('lottery_run')
    op.drop_table('lottery_room_type')
    op.drop_table('lottery_hotel')
    op.drop_table('inventory_partition')
