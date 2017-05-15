"""Intentionally empty for testing

Revision ID: fa51143177fe
Revises: 3723d12f8740
Create Date: 2017-05-15 18:27:43.275769

"""


# revision identifiers, used by Alembic.
revision = 'fa51143177fe'
down_revision = '3723d12f8740'
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
