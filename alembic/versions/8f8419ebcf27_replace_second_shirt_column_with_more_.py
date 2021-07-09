"""Replace second_shirt column with more flexible num_event_shirts column

Revision ID: 8f8419ebcf27
Revises: 4c9ae1c0db43
Create Date: 2019-07-19 16:31:05.311139

"""


# revision identifiers, used by Alembic.
revision = '8f8419ebcf27'
down_revision = '4c9ae1c0db43'
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
    op.add_column('attendee', sa.Column('num_event_shirts', sa.Integer(), server_default='0', nullable=False))
    op.drop_column('attendee', 'second_shirt')


def downgrade():
    op.add_column('attendee', sa.Column('second_shirt', sa.INTEGER(), server_default=sa.text('194196342'), autoincrement=False, nullable=False))
    op.drop_column('attendee', 'num_event_shirts')
