"""Tweak model receipt tracking

Revision ID: ec5e96beceb1
Revises: f2929b710d19
Create Date: 2023-03-02 05:24:36.220616

"""


# revision identifiers, used by Alembic.
revision = 'ec5e96beceb1'
down_revision = 'f2929b710d19'
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
    op.add_column('receipt_item', sa.Column('txn_id', sa.Uuid(as_uuid=False), nullable=True))
    op.create_foreign_key(op.f('fk_receipt_item_txn_id_receipt_transaction'), 'receipt_item', 'receipt_transaction', ['txn_id'], ['id'], ondelete='SET NULL')
    op.add_column('receipt_transaction', sa.Column('txn_total', sa.Integer(), server_default='0', nullable=False))
    op.execute('UPDATE RECEIPT_TRANSACTION SET REFUNDED = 0 WHERE REFUNDED IS NULL')
    op.alter_column('receipt_transaction', 'refunded',
               existing_type=sa.INTEGER(),
               server_default='0',
               nullable=False)
    op.add_column('receipt_item', sa.Column('comped', sa.Boolean(), server_default='False', nullable=False))
    op.add_column('receipt_item', sa.Column('reverted', sa.Boolean(), server_default='False', nullable=False))


def downgrade():
    op.alter_column('receipt_transaction', 'refunded',
               existing_type=sa.INTEGER(),
               nullable=True)
    op.drop_column('receipt_transaction', 'txn_total')
    op.drop_constraint(op.f('fk_receipt_item_txn_id_receipt_transaction'), 'receipt_item', type_='foreignkey')
    op.drop_column('receipt_item', 'txn_id')
    op.drop_column('receipt_item', 'reverted')
    op.drop_column('receipt_item', 'comped')
