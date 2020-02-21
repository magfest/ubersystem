"""Initial migration
Revision ID: af64b33e950a
Revises: 0b4ad67a27be
Create Date: 2018-05-08 23:18:35.150928
"""


# revision identifiers, used by Alembic.
revision = 'af64b33e950a'
down_revision = '0b4ad67a27be'
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
    op.add_column('attendee', sa.Column('print_pending', sa.Boolean(), server_default='False', nullable=False))
    op.add_column('attendee', sa.Column('times_printed', sa.Integer(), server_default='0', nullable=False))


def downgrade():
    op.drop_column('attendee', 'times_printed')
    op.drop_column('attendee', 'print_pending')