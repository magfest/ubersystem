"""Split lottery forms into steps and add info policy

Revision ID: 2e9e8e65e89c
Revises: 0578795f8d0b
Create Date: 2024-09-11 00:43:34.369454

"""


# revision identifiers, used by Alembic.
revision = '2e9e8e65e89c'
down_revision = '0578795f8d0b'
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
    op.add_column('lottery_application', sa.Column('room_step', sa.Integer(), server_default='0', nullable=False))
    op.add_column('lottery_application', sa.Column('suite_step', sa.Integer(), server_default='0', nullable=False))
    op.add_column('lottery_application', sa.Column('data_policy_accepted', sa.Boolean(), server_default='False', nullable=False))
    op.add_column('lottery_application', sa.Column('legal_first_name', sa.Unicode(), server_default='', nullable=False))
    op.add_column('lottery_application', sa.Column('legal_last_name', sa.Unicode(), server_default='', nullable=False))
    op.alter_column('lottery_application', 'attendee_id',
               existing_type=postgresql.UUID(),
               nullable=False)


def downgrade():
    op.alter_column('lottery_application', 'attendee_id',
               existing_type=postgresql.UUID(),
               nullable=True)
    op.drop_column('lottery_application', 'data_policy_accepted')
    op.drop_column('lottery_application', 'suite_step')
    op.drop_column('lottery_application', 'room_step')
    op.drop_column('lottery_application', 'legal_first_name')
    op.drop_column('lottery_application', 'legal_last_name')
