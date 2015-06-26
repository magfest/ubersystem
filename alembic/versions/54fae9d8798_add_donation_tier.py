"""Add new donation tier column

Revision ID: 54fae9d8798
Revises: 51e4adb4b60
Create Date: 2015-06-21 10:45:47.601690

"""

# revision identifiers, used by Alembic.
revision = '54fae9d8798'
down_revision = '51e4adb4b60'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column('attendee',
        sa.Column('donation_tier', sa.Integer(), server_default=243383191)
    )


def downgrade():
    op.drop_column('attendee', 'donation_tier')
