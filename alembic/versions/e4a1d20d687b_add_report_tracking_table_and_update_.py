"""Add report tracking table and update page view tracking table

Revision ID: e4a1d20d687b
Revises: 1ad8716bfc74
Create Date: 2024-02-16 16:42:29.601444

"""


# revision identifiers, used by Alembic.
revision = 'e4a1d20d687b'
down_revision = '1ad8716bfc74'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.types import UUID


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
    op.create_table('report_tracking',
    sa.Column('id', UUID(), nullable=False),
    sa.Column('when', DateTime(), nullable=False),
    sa.Column('who', sa.Unicode(), server_default='', nullable=False),
    sa.Column('page', sa.Unicode(), server_default='', nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_report_tracking')),
    sa.Column('params', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    )
    op.add_column('page_view_tracking', sa.Column('which', sa.Unicode(), server_default='', nullable=False))
    op.drop_column('page_view_tracking', 'what')


def downgrade():
    op.add_column('page_view_tracking', sa.Column('what', sa.VARCHAR(), server_default=sa.text("''::character varying"), autoincrement=False, nullable=False))
    op.drop_column('page_view_tracking', 'which')
    op.drop_table('report_tracking')
