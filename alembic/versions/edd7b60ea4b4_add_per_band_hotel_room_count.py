"""Add per-band hotel room count

Revision ID: edd7b60ea4b4
Revises: fc4b8eb3a35f
Create Date: 2017-06-22 15:36:41.797478

"""


# revision identifiers, used by Alembic.
revision = 'edd7b60ea4b4'
down_revision = 'fc4b8eb3a35f'
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
    op.add_column('band', sa.Column('num_hotel_rooms', sa.Integer(), server_default='1', nullable=False))


def downgrade():
    op.drop_column('band', 'num_hotel_rooms')
