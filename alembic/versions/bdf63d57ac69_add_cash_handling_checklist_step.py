"""Add cash-handling checklist step

Revision ID: bdf63d57ac69
Revises: 445fb71a63a3
Create Date: 2025-10-21 16:28:49.152781

"""


# revision identifiers, used by Alembic.
revision = 'bdf63d57ac69'
down_revision = '445fb71a63a3'
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
    op.add_column('attendee', sa.Column('reviewed_cash_handling', sa.DateTime(timezone=True), nullable=True))
    op.add_column('department', sa.Column('handles_cash', sa.Boolean(), server_default='False', nullable=False))


def downgrade():
    op.drop_column('department', 'handles_cash')
    op.drop_column('attendee', 'reviewed_cash_handling')
