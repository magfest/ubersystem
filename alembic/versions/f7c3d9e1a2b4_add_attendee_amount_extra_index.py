"""Add an attendee index for kick-in stock counts

Revision ID: f7c3d9e1a2b4
Revises: e5b2a7c91d40
Create Date: 2026-09-17 12:00:00.000000
"""


# revision identifiers, used by Alembic.
revision = 'f7c3d9e1a2b4'
down_revision = 'e5b2a7c91d40'
branch_labels = None
depends_on = None

from alembic import op


def upgrade():
    op.create_index('ix_attendee_amount_extra_badge_status', 'attendee', ['amount_extra', 'badge_status'],
                    unique=False, if_not_exists=True)


def downgrade():
    op.drop_index('ix_attendee_amount_extra_badge_status', table_name='attendee', if_exists=True)
