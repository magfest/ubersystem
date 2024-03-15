"""Add ReceiptInfo table

Revision ID: 6af647ca7d1f
Revises: 97418d392519
Create Date: 2023-11-09 03:54:46.149578

"""


# revision identifiers, used by Alembic.
revision = '6af647ca7d1f'
down_revision = '97418d392519'
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
    op.create_table('receipt_info',
    sa.Column('id', residue.UUID(), nullable=False),
    sa.Column('fk_email_model', sa.Unicode(), server_default='', nullable=False),
    sa.Column('fk_email_id', sa.Unicode(), server_default='', nullable=False),
    sa.Column('terminal_id', sa.Unicode(), server_default='', nullable=False),
    sa.Column('reference_id', sa.Unicode(), server_default='', nullable=False),
    sa.Column('receipt_html', sa.Unicode(), server_default='', nullable=False),
    sa.Column('card_data', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('txn_info', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('emv_data', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('signature', sa.Unicode(), server_default='', nullable=False),
    sa.Column('charged', residue.UTCDateTime(), nullable=False),
    sa.Column('voided', residue.UTCDateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_receipt_info'))
    )
    op.add_column('receipt_transaction', sa.Column('receipt_info_id', residue.UUID(), nullable=True))
    op.create_foreign_key(op.f('fk_receipt_transaction_receipt_info_id_receipt_info'), 'receipt_transaction', 'receipt_info', ['receipt_info_id'], ['id'], ondelete='SET NULL')


def downgrade():
    op.drop_constraint(op.f('fk_receipt_transaction_receipt_info_id_receipt_info'), 'receipt_transaction', type_='foreignkey')
    op.drop_column('receipt_transaction', 'receipt_info_id')
    op.drop_table('receipt_info')
