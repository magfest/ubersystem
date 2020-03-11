"""Add creator relationship to attendees

Revision ID: b960d6adb51a
Revises: c36659e7f238
Create Date: 2019-10-01 14:19:12.815190

"""


# revision identifiers, used by Alembic.
revision = 'b960d6adb51a'
down_revision = 'c36659e7f238'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa
import residue


try:
    is_sqlite = op.get_context().dialect.name == 'sqlite'
except Exception:
    is_sqlite = False

if is_sqlite:
    op.get_context().connection.execute('PRAGMA foreign_keys=ON;')
    utcnow_server_default = "(datetime('now', 'utc'))"
else:
    utcnow_server_default = "timezone('utc', current_timestamp)"

def sqlite_column_reflect_listener(inspector, table, column_info):
    """Adds parenthesis around SQLite datetime defaults for utcnow."""
    if column_info['default'] == "datetime('now', 'utc')":
        column_info['default'] = utcnow_server_default

sqlite_reflect_kwargs = {
    'listeners': [('column_reflect', sqlite_column_reflect_listener)]
}

# ===========================================================================
# HOWTO: Handle alter statements in SQLite
#
# def upgrade():
#     if is_sqlite:
#         with op.batch_alter_table('table_name', reflect_kwargs=sqlite_reflect_kwargs) as batch_op:
#             batch_op.alter_column('column_name', type_=sa.Unicode(), server_default='', nullable=False)
#     else:
#         op.alter_column('table_name', 'column_name', type_=sa.Unicode(), server_default='', nullable=False)
#
# ===========================================================================


def upgrade():
    op.add_column('attendee', sa.Column('creator_id', residue.UUID(), nullable=True))
    op.create_foreign_key(op.f('fk_attendee_creator_id_attendee'), 'attendee', 'attendee', ['creator_id'], ['id'])


def downgrade():
    op.drop_constraint(op.f('fk_attendee_creator_id_attendee'), 'attendee', type_='foreignkey')
    op.drop_column('attendee', 'creator_id')
