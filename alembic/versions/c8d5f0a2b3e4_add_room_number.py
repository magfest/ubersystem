"""Add room_number to room_assignment.

The physical room number at the hotel, usually assigned at or shortly
before check-in. Free text for now.

Revision ID: c8d5f0a2b3e4
Revises: b7c4e9a1f2d3
Create Date: 2026-07-09 00:00:00.000000
"""

revision = 'c8d5f0a2b3e4'
down_revision = 'b7c4e9a1f2d3'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column('room_assignment',
                  sa.Column('room_number', sa.Unicode(), nullable=True))


def downgrade():
    op.drop_column('room_assignment', 'room_number')
