"""Add missing indices

Revision ID: b36e0ca2ac50
Revises: 94aa84890142
Create Date: 2025-04-04 08:58:46.502699

"""


# revision identifiers, used by Alembic.
revision = 'b36e0ca2ac50'
down_revision = '94aa84890142'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
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
    op.drop_constraint('uq_indie_developer_attendee_id', 'indie_developer', type_='unique')
    op.create_unique_constraint(op.f('uq_lottery_application_attendee_id'), 'lottery_application', ['attendee_id'])
    op.create_index(op.f('ix_receipt_item_fk_id'), 'receipt_item', ['fk_id'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_receipt_item_fk_id'), table_name='receipt_item')
    op.drop_constraint(op.f('uq_lottery_application_attendee_id'), 'lottery_application', type_='unique')
    op.create_unique_constraint('uq_indie_developer_attendee_id', 'indie_developer', ['attendee_id'])
