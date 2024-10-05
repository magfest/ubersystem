"""Fix deleting groups with leaders

Revision ID: 9fb2b1c462c2
Revises: f1a8794a398f
Create Date: 2024-08-04 18:46:15.939539

"""


# revision identifiers, used by Alembic.
revision = '9fb2b1c462c2'
down_revision = 'f1a8794a398f'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa



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
    op.drop_constraint('fk_leader', 'group', type_='foreignkey')
    op.create_foreign_key('fk_leader', 'group', 'attendee', ['leader_id'], ['id'], ondelete='SET NULL', use_alter=True)


def downgrade():
    op.drop_constraint('fk_leader', 'group', type_='foreignkey')
    op.create_foreign_key('fk_leader', 'group', 'attendee', ['leader_id'], ['id'])
