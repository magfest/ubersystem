"""Intentionally empty for testing

Revision ID: 61f1dd158c0f
Revises: fa51143177fe
Create Date: 2017-05-15 18:35:53.915709

"""


# revision identifiers, used by Alembic.
revision = '61f1dd158c0f'
down_revision = 'fa51143177fe'
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
