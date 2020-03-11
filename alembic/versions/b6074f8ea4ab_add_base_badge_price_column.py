"""Add base_badge_price column

Revision ID: b6074f8ea4ab
Revises: 167243c0e86c
Create Date: 2017-07-14 04:16:59.504802

"""


# revision identifiers, used by Alembic.
revision = 'b6074f8ea4ab'
down_revision = '167243c0e86c'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa



try:
    is_sqlite = op.get_context().dialect.name == 'sqlite'
except:
    is_sqlite = False

if is_sqlite:
    op.get_context().connection.execute('PRAGMA foreign_keys=ON;')
    utcnow_server_default = "(datetime('now', 'utc'))"
else:
    utcnow_server_default = "timezone('utc', current_timestamp)"


def upgrade():
    op.add_column('attendee', sa.Column('base_badge_price', sa.Integer(), server_default='0', nullable=False))


def downgrade():
    op.drop_column('attendee', 'base_badge_price')
