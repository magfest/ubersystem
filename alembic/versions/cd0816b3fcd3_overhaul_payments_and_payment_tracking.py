"""Overhaul payments and payment tracking

Revision ID: cd0816b3fcd3
Revises: c7a439f29c1c
Create Date: 2022-07-22 05:00:23.972338

"""


# revision identifiers, used by Alembic.
revision = 'cd0816b3fcd3'
down_revision = 'c7a439f29c1c'
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
    op.create_table('model_receipt',
    sa.Column('id', residue.UUID(), nullable=False),
    sa.Column('invoice_num', sa.Integer(), server_default='0', nullable=False),
    sa.Column('owner_id', residue.UUID(), nullable=False),
    sa.Column('owner_model', sa.Unicode(), server_default='', nullable=False),
    sa.Column('closed', residue.UTCDateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_model_receipt'))
    )
    op.create_index(op.f('ix_model_receipt_owner_id'), 'model_receipt', ['owner_id'], unique=False)
    op.drop_table('receipt_item')
    op.create_table('receipt_item',
    sa.Column('id', residue.UUID(), nullable=False),
    sa.Column('receipt_id', residue.UUID(), nullable=True),
    sa.Column('amount', sa.Integer(), nullable=False),
    sa.Column('count', sa.Integer(), server_default='1', nullable=False),
    sa.Column('added', residue.UTCDateTime(), nullable=False),
    sa.Column('closed', residue.UTCDateTime(), nullable=True),
    sa.Column('who', sa.Unicode(), server_default='', nullable=False),
    sa.Column('desc', sa.Unicode(), server_default='', nullable=False),
    sa.Column('fk_id', residue.UUID(), nullable=True),
    sa.Column('fk_model', sa.Unicode(), server_default='', nullable=False),
    sa.Column('revert_change', residue.JSON(), server_default='{}', nullable=False),
    sa.ForeignKeyConstraint(['receipt_id'], ['model_receipt.id'], name=op.f('fk_receipt_item_receipt_id_model_receipt'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_receipt_item'))
    )
    op.create_index(op.f('ix_receipt_item_fk_id'), 'receipt_item', ['fk_id'], unique=False)
    op.create_table('receipt_transaction',
    sa.Column('id', residue.UUID(), nullable=False),
    sa.Column('receipt_id', residue.UUID(), nullable=True),
    sa.Column('intent_id', sa.Unicode(), server_default='', nullable=False),
    sa.Column('charge_id', sa.Unicode(), server_default='', nullable=False),
    sa.Column('refund_id', sa.Unicode(), server_default='', nullable=False),
    sa.Column('method', sa.Integer(), server_default='180350097', nullable=False),
    sa.Column('amount', sa.Integer(), nullable=False),
    sa.Column('added', residue.UTCDateTime(), nullable=False),
    sa.Column('cancelled', residue.UTCDateTime(), nullable=True),
    sa.Column('who', sa.Unicode(), server_default='', nullable=False),
    sa.Column('desc', sa.Unicode(), server_default='', nullable=False),
    sa.ForeignKeyConstraint(['receipt_id'], ['model_receipt.id'], name=op.f('fk_receipt_transaction_receipt_id_model_receipt'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_receipt_transaction'))
    )
    op.drop_table('stripe_transaction_attendee')
    op.drop_table('stripe_transaction_group')
    op.drop_table('stripe_transaction')
    op.drop_column('art_show_application', 'amount_paid')
    op.drop_column('art_show_application', 'base_price')
    op.drop_column('attendee', 'purchased_items')
    op.drop_column('attendee', 'payment_method')
    op.drop_column('attendee', 'amount_paid_override')
    op.drop_column('attendee', 'amount_refunded_override')
    op.drop_column('attendee', 'refunded_items')
    op.alter_column('attendee', 'base_badge_price', new_column_name='initial_badge_cost')
    op.drop_index('ix_marketplace_application_amount_paid', table_name='marketplace_application')
    op.drop_column('marketplace_application', 'amount_paid')
    op.drop_column('marketplace_application', 'base_price')


def downgrade():
    op.add_column('marketplace_application', sa.Column('base_price', sa.INTEGER(), server_default=sa.text('0'), autoincrement=False, nullable=False))
    op.add_column('marketplace_application', sa.Column('amount_paid', sa.INTEGER(), server_default=sa.text('0'), autoincrement=False, nullable=False))
    op.create_index('ix_marketplace_application_amount_paid', 'marketplace_application', ['amount_paid'], unique=False)
    op.add_column('attendee', sa.Column('refunded_items', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), autoincrement=False, nullable=False))
    op.add_column('attendee', sa.Column('amount_refunded_override', sa.INTEGER(), server_default=sa.text('0'), autoincrement=False, nullable=False))
    op.add_column('attendee', sa.Column('amount_paid_override', sa.INTEGER(), server_default=sa.text('0'), autoincrement=False, nullable=False))
    op.add_column('attendee', sa.Column('payment_method', sa.INTEGER(), autoincrement=False, nullable=True))
    op.add_column('attendee', sa.Column('purchased_items', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), autoincrement=False, nullable=False))
    op.alter_column('attendee', 'initial_badge_cost', new_column_name='base_badge_price')
    op.add_column('art_show_application', sa.Column('base_price', sa.INTEGER(), server_default=sa.text('0'), autoincrement=False, nullable=False))
    op.add_column('art_show_application', sa.Column('amount_paid', sa.INTEGER(), server_default=sa.text('0'), autoincrement=False, nullable=False))
    op.create_table('stripe_transaction',
    sa.Column('id', postgresql.UUID(), autoincrement=False, nullable=False),
    sa.Column('stripe_id', sa.VARCHAR(), server_default=sa.text("''::character varying"), autoincrement=False, nullable=True),
    sa.Column('type', sa.INTEGER(), server_default=sa.text('186441959'), autoincrement=False, nullable=False),
    sa.Column('amount', sa.INTEGER(), autoincrement=False, nullable=False),
    sa.Column('when', postgresql.TIMESTAMP(), autoincrement=False, nullable=False),
    sa.Column('who', sa.VARCHAR(), server_default=sa.text("''::character varying"), autoincrement=False, nullable=False),
    sa.Column('desc', sa.VARCHAR(), server_default=sa.text("''::character varying"), autoincrement=False, nullable=False),
    sa.PrimaryKeyConstraint('id', name='pk_stripe_transaction'),
    postgresql_ignore_search_path=False
    )
    op.create_table('stripe_transaction_group',
    sa.Column('id', postgresql.UUID(), autoincrement=False, nullable=False),
    sa.Column('txn_id', postgresql.UUID(), autoincrement=False, nullable=False),
    sa.Column('group_id', postgresql.UUID(), autoincrement=False, nullable=False),
    sa.Column('share', sa.INTEGER(), autoincrement=False, nullable=False),
    sa.ForeignKeyConstraint(['group_id'], ['group.id'], name='fk_stripe_transaction_group_group_id_group'),
    sa.ForeignKeyConstraint(['txn_id'], ['stripe_transaction.id'], name='fk_stripe_transaction_group_txn_id_stripe_transaction'),
    sa.PrimaryKeyConstraint('id', name='pk_stripe_transaction_group')
    )
    op.create_table('stripe_transaction_attendee',
    sa.Column('id', postgresql.UUID(), autoincrement=False, nullable=False),
    sa.Column('txn_id', postgresql.UUID(), autoincrement=False, nullable=False),
    sa.Column('attendee_id', postgresql.UUID(), autoincrement=False, nullable=False),
    sa.Column('share', sa.INTEGER(), autoincrement=False, nullable=False),
    sa.ForeignKeyConstraint(['attendee_id'], ['attendee.id'], name='fk_stripe_transaction_attendee_attendee_id_attendee'),
    sa.ForeignKeyConstraint(['txn_id'], ['stripe_transaction.id'], name='fk_stripe_transaction_attendee_txn_id_stripe_transaction'),
    sa.PrimaryKeyConstraint('id', name='pk_stripe_transaction_attendee')
    )
    op.drop_table('receipt_transaction')
    op.drop_index(op.f('ix_receipt_item_fk_id'), table_name='receipt_item')
    op.drop_table('receipt_item')
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
    op.drop_index(op.f('ix_model_receipt_owner_id'), table_name='model_receipt')
    op.drop_table('model_receipt')
