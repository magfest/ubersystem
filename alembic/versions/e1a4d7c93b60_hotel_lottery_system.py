"""Hotel lottery system.

Creates the hotel-lottery schema in one step: inventory (hotels, room types,
partitions, nightly quantities), the physical-room catalog and floor maps,
lottery runs, per-room assignments and occupants, room invites, waitlist
reveals, partition ownership/permissions, audit logging, import/export file
retention, and room-issue notes. Replaces the legacy room/hotel_requests
tables and migrates existing lottery applications onto the new
room_assignment model.

This consolidates the ten revisions the feature branch developed
incrementally (a7d3f0c1e2b4, b7c4e9a1f2d3, c8d5f0a2b3e4, d9e6a1b4c5f6,
e2b7c8d9f0a1, f3a9c2d1e4b7, a7d4e8f1b2c9, b8c5f2a9d3e6, c4e7b1a8f5d2,
d5f8c3b6a1e9), none of which ever reached production. Columns those
revisions added to tables created here are folded into the CREATE TABLE,
and the never-used physical_room.map_x/map_y pair is simply never created.

Revision ID: e1a4d7c93b60
Revises: 855b23e9aea1
Create Date: 2026-08-07 00:00:00.000000
"""

revision = 'e1a4d7c93b60'
down_revision = '855b23e9aea1'
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
    # Floor-map source (schema in uber.hotel.floormap) and the SVG rendered
    # from it for the room picker.
    sa.Column('map_yaml', sa.Unicode(), server_default='', nullable=False),
    sa.Column('map_svg', sa.Unicode(), server_default='', nullable=False),
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
    # Retains the raw file each hotel was sent, so the exports page can hand
    # back the exact bytes; `source` separates dashboard downloads from API
    # pulls.
    sa.Column('source', sa.Unicode(), server_default='', nullable=False),
    sa.Column('filename', sa.Unicode(), server_default='', nullable=False),
    sa.Column('content_type', sa.Unicode(), server_default='', nullable=False),
    sa.Column('filepath', sa.Unicode(), server_default='', nullable=False),
    sa.Column('size', sa.Integer(), server_default='0', nullable=False),
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
    # Which physical_room.type_code values this sellable block covers, so
    # catalog imports can resolve rooms to blocks by code.
    sa.Column('physical_room_types', sa.Unicode(), server_default='', nullable=False),
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

    # The physical-room catalog: one row per real room in a hotel building,
    # optionally categorized into a HotelRoomInventory block. Created here,
    # ahead of room_assignment, so that table's physical_room_id foreign key
    # can be declared inline. The floor map matches shapes to rooms by
    # number, so there are no per-room map coordinates.
    op.create_table(
        'physical_room',
        sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
        sa.Column('created', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_updated', sa.DateTime(timezone=True), nullable=False),
        sa.Column('external_id', postgresql.JSONB(astext_type=sa.Text()),
                  server_default='{}', nullable=False),
        sa.Column('last_synced', postgresql.JSONB(astext_type=sa.Text()),
                  server_default='{}', nullable=False),
        sa.Column('hotel_id', sa.Uuid(as_uuid=False), nullable=False),
        sa.Column('inventory_id', sa.Uuid(as_uuid=False), nullable=True),
        sa.Column('room_number', sa.Unicode(), server_default='', nullable=False),
        sa.Column('floor', sa.Unicode(), server_default='', nullable=False),
        sa.Column('ada', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('out_of_service', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('notes', sa.Unicode(), server_default='', nullable=False),
        # The hotel's own code for the room (T1, T2A, ...), and a
        # comma-separated list of accessibility feature tags.
        sa.Column('type_code', sa.Unicode(), server_default='', nullable=False),
        sa.Column('accessibility', sa.Unicode(), server_default='', nullable=False),
        sa.ForeignKeyConstraint(
            ['hotel_id'], ['lottery_hotel.id'],
            name=op.f('fk_physical_room_hotel_id_lottery_hotel'),
            ondelete='CASCADE'),
        sa.ForeignKeyConstraint(
            ['inventory_id'], ['hotel_room_inventory.id'],
            name=op.f('fk_physical_room_inventory_id_hotel_room_inventory')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_physical_room')),
        sa.UniqueConstraint('hotel_id', 'room_number',
                            name='uq_physical_room_number'),
    )
    op.create_index(op.f('ix_physical_room_hotel_id'),
                    'physical_room', ['hotel_id'], unique=False)
    op.create_index(op.f('ix_physical_room_inventory_id'),
                    'physical_room', ['inventory_id'], unique=False)

    # Undirected connecting-door edges.
    op.create_table(
        'physical_room_connection',
        sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
        sa.Column('created', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_updated', sa.DateTime(timezone=True), nullable=False),
        sa.Column('external_id', postgresql.JSONB(astext_type=sa.Text()),
                  server_default='{}', nullable=False),
        sa.Column('last_synced', postgresql.JSONB(astext_type=sa.Text()),
                  server_default='{}', nullable=False),
        sa.Column('room_a_id', sa.Uuid(as_uuid=False), nullable=False),
        sa.Column('room_b_id', sa.Uuid(as_uuid=False), nullable=False),
        sa.ForeignKeyConstraint(
            ['room_a_id'], ['physical_room.id'],
            name=op.f('fk_physical_room_connection_room_a_id_physical_room'),
            ondelete='CASCADE'),
        sa.ForeignKeyConstraint(
            ['room_b_id'], ['physical_room.id'],
            name=op.f('fk_physical_room_connection_room_b_id_physical_room'),
            ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_physical_room_connection')),
        sa.UniqueConstraint('room_a_id', 'room_b_id',
                            name='uq_physical_room_connection'),
    )

    op.add_column('lottery_application', sa.Column('assigned_inventory_id', sa.Uuid(as_uuid=False), nullable=True))
    op.add_column('lottery_application', sa.Column('partition_id', sa.Uuid(as_uuid=False), nullable=True))
    op.add_column('lottery_application', sa.Column('export_locked', sa.Boolean(), server_default=sa.text('false'), nullable=False))
    op.add_column('lottery_application', sa.Column('invite_token', sa.Unicode(), server_default='', nullable=False))
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
    op.add_column('lottery_application', sa.Column('address1', sa.Unicode(), server_default='', nullable=False))
    op.add_column('lottery_application', sa.Column('address2', sa.Unicode(), server_default='', nullable=False))
    op.add_column('lottery_application', sa.Column('city', sa.Unicode(), server_default='', nullable=False))
    op.add_column('lottery_application', sa.Column('region', sa.Unicode(), server_default='', nullable=False))
    op.add_column('lottery_application', sa.Column('zip_code', sa.Unicode(), server_default='', nullable=False))
    op.add_column('lottery_application', sa.Column('country', sa.Unicode(), server_default='', nullable=False))
    op.add_column('lottery_application', sa.Column('hotel_confirmation_number', sa.Unicode(), nullable=True))
    op.add_column('lottery_application', sa.Column('special_requests', sa.Unicode(), server_default='', nullable=False))
    op.add_column('lottery_application', sa.Column('hotel_rewards_number', sa.Unicode(), server_default='', nullable=False))
    op.add_column('lottery_application', sa.Column('last_modified_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('lottery_application', sa.Column('lottery_run_id', sa.Uuid(as_uuid=False), nullable=True))
    op.create_foreign_key(op.f('fk_lottery_application_invited_by_id_lottery_application'), 'lottery_application', 'lottery_application', ['invited_by_id'], ['id'])
    op.create_foreign_key(op.f('fk_lottery_application_assigned_inventory_id_hotel_room_inventory'), 'lottery_application', 'hotel_room_inventory', ['assigned_inventory_id'], ['id'])
    op.create_foreign_key(op.f('fk_lottery_application_lottery_run_id_lottery_run'), 'lottery_application', 'lottery_run', ['lottery_run_id'], ['id'])
    op.create_foreign_key(op.f('fk_lottery_application_partition_id_inventory_partition'), 'lottery_application', 'inventory_partition', ['partition_id'], ['id'])
    # final_status_hidden / booking_url_hidden / assigned_room_type /
    # assigned_suite_type / assigned_hotel are dropped later, together with
    # LEGACY_COLUMNS, after the legacy-award backfill below has converted
    # their data into room_assignment rows.

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
        sa.Column('physical_room_id', sa.Uuid(as_uuid=False), nullable=True),

        # The physical room number at the hotel, usually assigned at or
        # shortly before check-in. Free text, and independent of
        # physical_room_id, which may be unset when the number is known.
        sa.Column('room_number', sa.Unicode(), nullable=True),
        # Marks placements made by the rooming board's auto-assign pass, so
        # clearing can distinguish them from ones an admin made by hand.
        sa.Column('physical_room_auto', sa.Boolean(),
                  server_default='false', nullable=False),

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
        sa.ForeignKeyConstraint(['physical_room_id'], ['physical_room.id'],
                                name=op.f('fk_room_assignment_physical_room_id_physical_room')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_room_assignment')),
    )

    op.create_index(op.f('ix_room_assignment_physical_room_id'),
                    'room_assignment', ['physical_room_id'], unique=False)
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

    # Legacy-award backfill: databases coming straight from main store awards
    # as config-enum ints (assigned_hotel / assigned_room_type /
    # assigned_suite_type) plus dates and booking_url directly on the
    # application - assigned_inventory_id doesn't exist there, so the
    # intermediate backfill above matches nothing. The enum ints are hashes
    # of config option names that were removed from configspec, so the
    # original display names are unrecoverable here; instead, each distinct
    # legacy value becomes an inactive "Legacy ..." placeholder
    # hotel/room-type/inventory row (rename them in the admin afterwards)
    # and each awarded application gets a room_assignment pointing at the
    # matching placeholder. Preference CSVs (hotel_preference etc.) are NOT
    # converted - they only affect future runs, which should use the real,
    # admin-entered inventory.
    #
    # Every statement no-ops on databases with no legacy award data.
    op.execute(sa.text("""
        CREATE TEMPORARY TABLE _legacy_hotel_map AS
        SELECT val,
               gen_random_uuid() AS new_id,
               row_number() OVER (ORDER BY val) AS ord
        FROM (SELECT DISTINCT assigned_hotel AS val
              FROM lottery_application
              WHERE assigned_hotel IS NOT NULL) s
    """))
    op.execute(sa.text("""
        CREATE TEMPORARY TABLE _legacy_type_map AS
        SELECT val, is_suite,
               gen_random_uuid() AS new_id,
               row_number() OVER (PARTITION BY is_suite ORDER BY val) AS ord
        FROM (SELECT DISTINCT assigned_room_type AS val, false AS is_suite
              FROM lottery_application WHERE assigned_room_type IS NOT NULL
              UNION
              SELECT DISTINCT assigned_suite_type AS val, true AS is_suite
              FROM lottery_application WHERE assigned_suite_type IS NOT NULL) s
    """))
    op.execute(sa.text("""
        INSERT INTO lottery_hotel (
            id, created, last_updated, external_id, last_synced,
            name, export_name, description, description_right, footnote, active)
        SELECT new_id, timezone('utc', now()), timezone('utc', now()),
               '{}'::jsonb, '{}'::jsonb,
               'Legacy Hotel ' || ord, '', '', '', '', false
        FROM _legacy_hotel_map
    """))
    op.execute(sa.text("""
        INSERT INTO lottery_room_type (
            id, created, last_updated, external_id, last_synced,
            name, export_name, description, description_right, footnote,
            capacity, min_capacity, is_suite, active)
        SELECT new_id, timezone('utc', now()), timezone('utc', now()),
               '{}'::jsonb, '{}'::jsonb,
               CASE WHEN is_suite THEN 'Legacy Suite Type ' ELSE 'Legacy Room Type ' END || ord,
               '', '', '', '', 4, 1, is_suite, false
        FROM _legacy_type_map
    """))
    op.execute(sa.text("""
        CREATE TEMPORARY TABLE _legacy_inv_map AS
        SELECT s.h_val, s.t_val, s.t_is_suite,
               gen_random_uuid() AS new_id,
               hm.new_id AS hotel_id,
               tm.new_id AS type_id,
               COALESCE('Legacy Hotel ' || hm.ord, 'Unknown hotel')
                   || ' - '
                   || COALESCE(
                        CASE WHEN s.t_is_suite THEN 'Legacy Suite Type '
                             ELSE 'Legacy Room Type ' END || tm.ord,
                        'unknown type') AS block_name
        FROM (SELECT DISTINCT
                  assigned_hotel AS h_val,
                  COALESCE(assigned_suite_type, assigned_room_type) AS t_val,
                  (assigned_suite_type IS NOT NULL) AS t_is_suite
              FROM lottery_application
              WHERE assigned_hotel IS NOT NULL
                 OR assigned_room_type IS NOT NULL
                 OR assigned_suite_type IS NOT NULL) s
        LEFT JOIN _legacy_hotel_map hm ON hm.val = s.h_val
        LEFT JOIN _legacy_type_map tm
               ON tm.val = s.t_val AND tm.is_suite = s.t_is_suite
    """))
    op.execute(sa.text("""
        INSERT INTO hotel_room_inventory (
            id, created, last_updated, external_id, last_synced,
            hotel_id, room_type_id, suite_type_id,
            quantity, capacity, min_capacity, name, is_suite, active,
            vault_reference, info_url, price, staff_price)
        SELECT new_id, timezone('utc', now()), timezone('utc', now()),
               '{}'::jsonb, '{}'::jsonb,
               hotel_id,
               CASE WHEN NOT t_is_suite THEN type_id END,
               CASE WHEN t_is_suite THEN type_id END,
               0, 4, 1, block_name, t_is_suite, false,
               NULL, '', '', ''
        FROM _legacy_inv_map
    """))
    op.execute(sa.text(f"""
        INSERT INTO room_assignment (
            id, created, last_updated, external_id, last_synced,
            attendee_id, inventory_id, lottery_application_id,
            assignment_reason, status, require_cc,
            assigned_check_in_date, assigned_check_out_date, deposit_cutoff_date,
            booking_url, special_requests, hotel_rewards_number,
            address1, address2, city, region, zip_code, country,
            last_modified_at, admin_notes
        )
        SELECT
            gen_random_uuid(),
            timezone('utc', now()), timezone('utc', now()),
            '{{}}'::jsonb, '{{}}'::jsonb,
            la.attendee_id, im.new_id, la.id,
            {c.MIGRATED},
            CASE
                WHEN la.status = {c.SECURED} THEN {c.SECURED}
                WHEN la.status = {c.CANCELLED} THEN {c.CANCELLED}
                ELSE {c.ASSIGNED}
            END,
            true,
            la.assigned_check_in_date, la.assigned_check_out_date,
            la.deposit_cutoff_date,
            COALESCE(la.booking_url, ''), COALESCE(la.special_requests, ''),
            COALESCE(la.hotel_rewards_number, ''),
            COALESCE(la.address1, ''), COALESCE(la.address2, ''),
            COALESCE(la.city, ''), COALESCE(la.region, ''),
            COALESCE(la.zip_code, ''), COALESCE(la.country, ''),
            la.last_modified_at,
            'Migrated from pre-lottery-system award (legacy enum values: hotel='
                || COALESCE(la.assigned_hotel::text, '-')
                || ', room_type=' || COALESCE(la.assigned_room_type::text, '-')
                || ', suite_type=' || COALESCE(la.assigned_suite_type::text, '-') || ')'
        FROM lottery_application la
        LEFT JOIN _legacy_inv_map im
               ON im.h_val IS NOT DISTINCT FROM la.assigned_hotel
              AND im.t_val IS NOT DISTINCT FROM
                  COALESCE(la.assigned_suite_type, la.assigned_room_type)
              AND im.t_is_suite = (la.assigned_suite_type IS NOT NULL)
        WHERE la.attendee_id IS NOT NULL
          AND la.assigned_inventory_id IS NULL
          AND (la.assigned_hotel IS NOT NULL
               OR la.assigned_room_type IS NOT NULL
               OR la.assigned_suite_type IS NOT NULL)
    """))
    op.execute(sa.text("""
        DROP TABLE IF EXISTS _legacy_inv_map, _legacy_type_map, _legacy_hotel_map
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
        # Whose room the entry is about. Kept separate from target_id so the
        # activity tab can still name the attendee once the assignment row
        # itself is gone.
        sa.Column('attendee_id', sa.Uuid(as_uuid=False), nullable=True),
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
        sa.ForeignKeyConstraint(['attendee_id'], ['attendee.id'],
                                name=op.f('fk_partition_audit_log_attendee_id_attendee'),
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
    # The enum award columns and hidden flags are dropped here too, now that
    # both backfills above have consumed them.
    with op.batch_alter_table('lottery_application') as batch_op:
        batch_op.drop_constraint(
            op.f('fk_lottery_application_assigned_inventory_id_hotel_room_inventory'),
            type_='foreignkey')
        batch_op.drop_column('assigned_inventory_id')
        for col in LEGACY_COLUMNS:
            batch_op.drop_column(col)
        batch_op.drop_column('final_status_hidden')
        batch_op.drop_column('booking_url_hidden')
        batch_op.drop_column('assigned_room_type')
        batch_op.drop_column('assigned_suite_type')
        batch_op.drop_column('assigned_hotel')

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

    op.create_table('hotel_import_file',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('created', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_updated', sa.DateTime(timezone=True), nullable=False),
    sa.Column('external_id', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('last_synced', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('hotel_id', sa.Uuid(as_uuid=False), nullable=True),
    sa.Column('filename', sa.Unicode(), nullable=False),
    sa.Column('content_type', sa.Unicode(), nullable=False),
    sa.Column('filepath', sa.Unicode(), nullable=False),
    sa.Column('size', sa.Integer(), nullable=False),
    sa.Column('source', sa.Unicode(), nullable=False),
    sa.Column('uploaded_by', sa.Unicode(), nullable=False),
    sa.Column('uploaded_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_count', sa.Integer(), nullable=False),
    sa.Column('unchanged_count', sa.Integer(), nullable=False),
    sa.Column('note', sa.Unicode(), nullable=False),
    # Brackets the moment this file's rows were applied, so the exports page
    # can show which room changes it caused (the change feed has no link
    # back to the uploaded file).
    sa.Column('applied_from', sa.DateTime(timezone=True), nullable=True),
    sa.Column('applied_to', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['hotel_id'], ['lottery_hotel.id'], name=op.f('fk_hotel_import_file_hotel_id_lottery_hotel')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_hotel_import_file'))
    )


def downgrade():
    op.drop_table('hotel_import_file')

    # room_assignment references physical_room, so its foreign key goes
    # before the catalog tables; the table itself is dropped further down.
    op.drop_index(op.f('ix_room_assignment_physical_room_id'),
                  table_name='room_assignment')
    op.drop_constraint(
        op.f('fk_room_assignment_physical_room_id_physical_room'),
        'room_assignment', type_='foreignkey')
    op.drop_column('room_assignment', 'physical_room_id')
    op.drop_table('physical_room_connection')
    op.drop_index(op.f('ix_physical_room_inventory_id'),
                  table_name='physical_room')
    op.drop_index(op.f('ix_physical_room_hotel_id'),
                  table_name='physical_room')
    op.drop_table('physical_room')

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
