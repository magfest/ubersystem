"""Add per-occupant stay dates to room_assignment_occupant

Revision ID: 8b1f4d6e2a90
Revises: 3c9e2a7f41d8
Create Date: 2026-11-09 12:00:00.000000
"""


# revision identifiers, used by Alembic.
revision = '8b1f4d6e2a90'
down_revision = '3c9e2a7f41d8'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column('room_assignment_occupant', sa.Column('check_in_date', sa.Date(), nullable=True))
    op.add_column('room_assignment_occupant', sa.Column('check_out_date', sa.Date(), nullable=True))


def downgrade():
    op.drop_column('room_assignment_occupant', 'check_out_date')
    op.drop_column('room_assignment_occupant', 'check_in_date')
