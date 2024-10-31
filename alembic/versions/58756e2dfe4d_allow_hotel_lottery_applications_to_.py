"""Allow hotel lottery applications to have no attendee

Revision ID: 58756e2dfe4d
Revises: 128e7228f182
Create Date: 2024-10-31 17:36:53.320109

"""


# revision identifiers, used by Alembic.
revision = '58756e2dfe4d'
down_revision = '128e7228f182'
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
    op.alter_column('lottery_application', 'attendee_id',
               existing_type=postgresql.UUID(),
               nullable=True)
    op.create_unique_constraint(op.f('uq_lottery_application_attendee_id'), 'lottery_application', ['attendee_id'])


def downgrade():
    op.drop_constraint(op.f('uq_lottery_application_attendee_id'), 'lottery_application', type_='unique')
    op.alter_column('lottery_application', 'attendee_id',
               existing_type=postgresql.UUID(),
               nullable=False)
