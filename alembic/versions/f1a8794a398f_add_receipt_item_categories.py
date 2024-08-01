"""Add receipt item categories

Revision ID: f1a8794a398f
Revises: 3fe61d6e4837
Create Date: 2024-07-19 05:33:32.847752

"""


# revision identifiers, used by Alembic.
revision = 'f1a8794a398f'
down_revision = '3fe61d6e4837'
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
    op.add_column('receipt_transaction', sa.Column('department', sa.Integer(), server_default='208882980', nullable=False))
    op.add_column('receipt_item', sa.Column('department', sa.Integer(), server_default='208882980', nullable=False))
    op.add_column('receipt_item', sa.Column('category', sa.Integer(), server_default='224685583', nullable=False))


def downgrade():
    op.drop_column('receipt_transaction', 'department')
    op.drop_column('receipt_item', 'category')
    op.drop_column('receipt_item', 'department')
