"""Add the physical-room catalog.

physical_room: one row per real room in a hotel building, optionally
categorized into a HotelRoomInventory block. physical_room_connection:
undirected connecting-door edges. room_assignment.physical_room_id links
a booking to its (optional) physical room.

Revision ID: d9e6a1b4c5f6
Revises: c8d5f0a2b3e4
Create Date: 2026-07-09 00:00:00.000000
"""

revision = 'd9e6a1b4c5f6'
down_revision = 'c8d5f0a2b3e4'
branch_labels = None
depends_on = None

from alembic import op
from sqlalchemy.dialects import postgresql
import sqlalchemy as sa


def upgrade():
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
        sa.Column('map_x', sa.Integer(), nullable=True),
        sa.Column('map_y', sa.Integer(), nullable=True),
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

    op.add_column('room_assignment',
                  sa.Column('physical_room_id', sa.Uuid(as_uuid=False),
                            nullable=True))
    op.create_foreign_key(
        op.f('fk_room_assignment_physical_room_id_physical_room'),
        'room_assignment', 'physical_room', ['physical_room_id'], ['id'])
    op.create_index(op.f('ix_room_assignment_physical_room_id'),
                    'room_assignment', ['physical_room_id'], unique=False)


def downgrade():
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
