"""Add purchaser_id to ReceiptItem

Revision ID: c198327b52b6
Revises: 6d8333eaf58a
Create Date: 2025-05-01 20:17:26.359259

"""


# revision identifiers, used by Alembic.
revision = 'c198327b52b6'
down_revision = '6d8333eaf58a'
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
    op.add_column('receipt_item', sa.Column('purchaser_id', residue.UUID(), nullable=True))
    op.create_index(op.f('ix_receipt_item_purchaser_id'), 'receipt_item', ['purchaser_id'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_receipt_item_purchaser_id'), table_name='receipt_item')
    op.drop_column('receipt_item', 'purchaser_id')
