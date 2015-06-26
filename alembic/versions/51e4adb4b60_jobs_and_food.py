"""Add WatchList table

Revision ID: 51e4adb4b60
Revises: 16acd13b4aa1
Create Date: 2015-06-19 12:06:10.753671

"""

# revision identifiers, used by Alembic.
revision = '51e4adb4b60'
down_revision = '16acd13b4aa1'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa
from sideboard.lib.sa import UUID


def upgrade():
    op.drop_table('room_assignment')
    op.drop_table('room')
    op.drop_table('checkout')


def downgrade():
    pass
