"""Add occupant_message to room_assignment

Revision ID: c4d7a1e93b52
Revises: 908bbf2c2133
Create Date: 2026-11-18 12:00:00.000000
"""


# revision identifiers, used by Alembic.
revision = 'c4d7a1e93b52'
down_revision = '908bbf2c2133'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column('room_assignment', sa.Column('occupant_message', sa.Unicode(), server_default='', nullable=False))


def downgrade():
    op.drop_column('room_assignment', 'occupant_message')
