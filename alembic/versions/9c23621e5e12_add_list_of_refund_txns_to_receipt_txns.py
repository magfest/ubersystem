"""Add list of refund txns to receipt txns

Revision ID: 9c23621e5e12
Revises: f01a2ad10d79
Create Date: 2024-11-06 17:59:12.695586

"""


# revision identifiers, used by Alembic.
revision = '9c23621e5e12'
down_revision = 'f01a2ad10d79'
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
    op.create_index(op.f('ix_receipt_item_fk_id'), 'receipt_item', ['fk_id'], unique=False)
    op.add_column('receipt_transaction', sa.Column('refunded_txn_id', residue.UUID(), nullable=True))
    op.create_foreign_key(op.f('fk_receipt_transaction_refunded_txn_id_receipt_transaction'), 'receipt_transaction', 'receipt_transaction', ['refunded_txn_id'], ['id'], ondelete='SET NULL')


def downgrade():
    op.drop_constraint(op.f('fk_receipt_transaction_refunded_txn_id_receipt_transaction'), 'receipt_transaction', type_='foreignkey')
    op.drop_column('receipt_transaction', 'refunded_txn_id')
    op.drop_index(op.f('ix_receipt_item_fk_id'), table_name='receipt_item')
