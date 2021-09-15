"""Refactor ReceiptItem table to record current cost items

Revision ID: a9b36ffb5ff7
Revises: 0a3de3158ae9
Create Date: 2020-02-06 13:24:09.874196

"""


# revision identifiers, used by Alembic.
revision = 'a9b36ffb5ff7'
down_revision = '0a3de3158ae9'
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
    op.add_column('attendee', sa.Column('refunded_items', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False))
    op.add_column('group', sa.Column('purchased_items', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False))
    op.add_column('group', sa.Column('refunded_items', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False))
    op.add_column('receipt_item', sa.Column('cost_snapshot', residue.types.JSON(), server_default='{}', nullable=False))
    op.add_column('receipt_item', sa.Column('refund_snapshot', residue.types.JSON(), server_default='{}', nullable=False))
    op.drop_column('receipt_item', 'item_type')
    op.drop_column('receipt_item', 'fk_id')
    op.drop_column('receipt_item', 'model')


def downgrade():
    op.drop_column('attendee', 'refunded_items')
    op.drop_column('group', 'purchased_items')
    op.drop_column('group', 'refunded_items')
    op.add_column('receipt_item', sa.Column('model', sa.VARCHAR(), server_default=sa.text("''::character varying"), autoincrement=False, nullable=False))
    op.add_column('receipt_item', sa.Column('fk_id', postgresql.UUID(), autoincrement=False, nullable=True))
    op.add_column('receipt_item', sa.Column('item_type', sa.INTEGER(), server_default=sa.text('224685583'), autoincrement=False, nullable=False))
    op.drop_column('receipt_item', 'cost_snapshot')
    op.drop_column('receipt_item', 'refund_snapshot')
