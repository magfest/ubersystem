"""Add creator relationship to groups

Revision ID: d42d4e52cfab
Revises: b960d6adb51a
Create Date: 2019-11-01 02:43:25.303666

"""


# revision identifiers, used by Alembic.
revision = 'd42d4e52cfab'
down_revision = 'b960d6adb51a'
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
    op.add_column('group', sa.Column('creator_id', residue.UUID(), nullable=True))
    op.create_foreign_key(op.f('fk_group_creator_id_attendee'), 'group', 'attendee', ['creator_id'], ['id'])


def downgrade():
    op.drop_constraint(op.f('fk_group_creator_id_attendee'), 'group', type_='foreignkey')
    op.drop_column('group', 'creator_id')
