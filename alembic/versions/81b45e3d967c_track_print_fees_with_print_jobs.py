"""Track print fees with print jobs

Revision ID: 81b45e3d967c
Revises: 40ec91ad7a74
Create Date: 2021-11-27 00:42:34.973833

"""


# revision identifiers, used by Alembic.
revision = '81b45e3d967c'
down_revision = '40ec91ad7a74'
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
    op.drop_column('attendee', 'print_pending')
    op.drop_column('attendee', 'times_printed')
    op.add_column('print_job', sa.Column('print_fee', sa.Integer(), server_default='0', nullable=False))


def downgrade():
    op.drop_column('print_job', 'print_fee')
    op.add_column('attendee', sa.Column('times_printed', sa.INTEGER(), server_default=sa.text('0'), autoincrement=False, nullable=False))
    op.add_column('attendee', sa.Column('print_pending', sa.BOOLEAN(), server_default=sa.text('false'), autoincrement=False, nullable=False))
