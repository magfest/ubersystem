"""Intentionally empty for testing

Revision ID: 39579e9fe443
Revises: 61f1dd158c0f
Create Date: 2017-05-15 18:36:12.231153

"""


# revision identifiers, used by Alembic.
revision = '39579e9fe443'
down_revision = '61f1dd158c0f'
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
    pass


def downgrade():
    pass
