"""Add supervisor column to tracking tables

Revision ID: f85c05a4410e
Revises: ecb1983d7dfd
Create Date: 2024-11-21 17:03:10.778841

"""


# revision identifiers, used by Alembic.
revision = 'f85c05a4410e'
down_revision = 'ecb1983d7dfd'
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
    op.add_column('page_view_tracking', sa.Column('supervisor', sa.Unicode(), server_default='', nullable=False))
    op.add_column('report_tracking', sa.Column('supervisor', sa.Unicode(), server_default='', nullable=False))
    op.add_column('tracking', sa.Column('supervisor', sa.Unicode(), server_default='', nullable=False))


def downgrade():
    op.drop_column('tracking', 'supervisor')
    op.drop_column('report_tracking', 'supervisor')
    op.drop_column('page_view_tracking', 'supervisor')
