"""Intentionally empty for testing

Revision ID: 2fffa9fad4d1
Revises: c1c625051e6c
Create Date: 2017-05-15 17:34:27.046037

"""


# revision identifiers, used by Alembic.
revision = '2fffa9fad4d1'
down_revision = 'c1c625051e6c'
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
