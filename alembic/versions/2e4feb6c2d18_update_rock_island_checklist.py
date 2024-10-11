"""Update rock island checklist

Revision ID: 2e4feb6c2d18
Revises: 9b657ae4c4ac
Create Date: 2024-10-11 11:40:31.124938

"""


# revision identifiers, used by Alembic.
revision = '2e4feb6c2d18'
down_revision = '9b657ae4c4ac'
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
    op.add_column('guest_merch', sa.Column('inventory_updated', residue.UTCDateTime(), nullable=True))
    op.add_column('guest_merch', sa.Column('delivery_method', sa.Integer(), nullable=True))
    op.add_column('guest_merch', sa.Column('payout_method', sa.Integer(), nullable=True))
    op.add_column('guest_merch', sa.Column('paypal_email', sa.Unicode(), server_default='', nullable=False))
    op.add_column('guest_merch', sa.Column('check_payable', sa.Unicode(), server_default='', nullable=False))
    op.add_column('guest_merch', sa.Column('check_zip_code', sa.Unicode(), server_default='', nullable=False))
    op.add_column('guest_merch', sa.Column('check_address1', sa.Unicode(), server_default='', nullable=False))
    op.add_column('guest_merch', sa.Column('check_address2', sa.Unicode(), server_default='', nullable=False))
    op.add_column('guest_merch', sa.Column('check_city', sa.Unicode(), server_default='', nullable=False))
    op.add_column('guest_merch', sa.Column('check_region', sa.Unicode(), server_default='', nullable=False))
    op.add_column('guest_merch', sa.Column('check_country', sa.Unicode(), server_default='', nullable=False))
    op.add_column('guest_merch', sa.Column('arrival_plans', sa.Unicode(), server_default='', nullable=False))
    op.add_column('guest_merch', sa.Column('merch_events', sa.Unicode(), server_default='', nullable=False))
    op.drop_column('guest_merch', 'bringing_boxes')


def downgrade():
    op.add_column('guest_merch', sa.Column('bringing_boxes', sa.VARCHAR(), server_default=sa.text("''::character varying"), autoincrement=False, nullable=False))
    op.drop_column('guest_merch', 'merch_events')
    op.drop_column('guest_merch', 'arrival_plans')
    op.drop_column('guest_merch', 'check_country')
    op.drop_column('guest_merch', 'check_region')
    op.drop_column('guest_merch', 'check_city')
    op.drop_column('guest_merch', 'check_address2')
    op.drop_column('guest_merch', 'check_address1')
    op.drop_column('guest_merch', 'check_zip_code')
    op.drop_column('guest_merch', 'check_payable')
    op.drop_column('guest_merch', 'paypal_email')
    op.drop_column('guest_merch', 'payout_method')
    op.drop_column('guest_merch', 'delivery_method')
    op.drop_column('guest_merch', 'inventory_updated')
