"""Initial alter statements

Revision ID: 1ed43776064f
Revises: ff7e7ae6d711
Create Date: 2017-04-23 19:06:40.644549

"""


# revision identifiers, used by Alembic.
revision = '1ed43776064f'
down_revision = 'ff7e7ae6d711'
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
    if not is_sqlite:
        op.create_foreign_key('fk_leader', 'group', 'attendee', ['leader_id'], ['id'], use_alter=True)


def downgrade():
    if not is_sqlite:
        op.drop_constraint('fk_leader', 'group', type_='foreignkey')
