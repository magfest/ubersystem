"""Add ReceiptItem table for tracking

Revision ID: 3c0edc37569e
Revises: 9e721eb0b45c
Create Date: 2019-08-28 16:50:28.789965

"""


# revision identifiers, used by Alembic.
revision = '3c0edc37569e'
down_revision = '9e721eb0b45c'
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
    op.create_table('receipt_item',
    sa.Column('id', residue.UUID(), nullable=False),
    sa.Column('attendee_id', residue.UUID(), nullable=True),
    sa.Column('group_id', residue.UUID(), nullable=True),
    sa.Column('txn_id', residue.UUID(), nullable=True),
    sa.Column('fk_id', residue.UUID(), nullable=True),
    sa.Column('model', sa.Unicode(), server_default='', nullable=False),
    sa.Column('txn_type', sa.Integer(), server_default='186441959', nullable=False),
    sa.Column('item_type', sa.Integer(), server_default='224685583', nullable=False),
    sa.Column('amount', sa.Integer(), nullable=False),
    sa.Column('when', residue.UTCDateTime(), nullable=False),
    sa.Column('who', sa.Unicode(), server_default='', nullable=False),
    sa.Column('desc', sa.Unicode(), server_default='', nullable=False),
    sa.ForeignKeyConstraint(['attendee_id'], ['attendee.id'], name=op.f('fk_receipt_item_attendee_id_attendee'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['group_id'], ['group.id'], name=op.f('fk_receipt_item_group_id_group'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['txn_id'], ['stripe_transaction.id'], name=op.f('fk_receipt_item_txn_id_stripe_transaction'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_receipt_item'))
    )


def downgrade():
    op.drop_table('receipt_item')
