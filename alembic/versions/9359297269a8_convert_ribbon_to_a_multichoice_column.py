"""Convert ribbon to a multichoice column.

Revision ID: 9359297269a8
Revises: 167243c0e86c
Create Date: 2017-07-21 09:18:38.444238

"""


# revision identifiers, used by Alembic.
revision = '9359297269a8'
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
    op.alter_column('attendee', 'ribbon', type_=sa.Unicode(), server_default = '', nullable = False)


def downgrade():
    op.alter_column('attendee', 'ribbon', type_=sa.Integer(), server_default=154973361, nullable=False)
