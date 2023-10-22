"""Allow API and Print jobs to not have admin IDs

Revision ID: a4a79802ba51
Revises: a5d2a3700b1a
Create Date: 2022-08-18 23:48:31.985975

"""


# revision identifiers, used by Alembic.
revision = 'a4a79802ba51'
down_revision = 'a5d2a3700b1a'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


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
    op.alter_column('api_job', 'admin_id',
               existing_type=postgresql.UUID(),
               nullable=True)
    op.alter_column('print_job', 'admin_id',
               existing_type=postgresql.UUID(),
               nullable=True)


def downgrade():
    op.alter_column('print_job', 'admin_id',
               existing_type=postgresql.UUID(),
               nullable=False)
    op.alter_column('api_job', 'admin_id',
               existing_type=postgresql.UUID(),
               nullable=False)
