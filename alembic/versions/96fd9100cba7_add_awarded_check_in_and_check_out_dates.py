"""Add awarded check-in and check-out dates

Revision ID: 96fd9100cba7
Revises: 21cb18083129
Create Date: 2025-08-06 19:27:25.826959

"""


# revision identifiers, used by Alembic.
revision = '96fd9100cba7'
down_revision = '21cb18083129'
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
    op.add_column('lottery_application', sa.Column('assigned_check_in_date', sa.Date(), nullable=True))
    op.add_column('lottery_application', sa.Column('assigned_check_out_date', sa.Date(), nullable=True))


def downgrade():
    op.drop_column('lottery_application', 'assigned_check_out_date')
    op.drop_column('lottery_application', 'assigned_check_in_date')
