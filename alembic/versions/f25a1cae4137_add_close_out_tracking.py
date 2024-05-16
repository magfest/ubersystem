"""Add close out tracking

Revision ID: f25a1cae4137
Revises: 66160e007b0a
Create Date: 2023-11-23 03:22:26.403583

"""


# revision identifiers, used by Alembic.
revision = 'f25a1cae4137'
down_revision = '66160e007b0a'
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
    op.create_table('terminal_settlement',
    sa.Column('batch_timestamp', sa.Unicode(), server_default='', nullable=False),
    sa.Column('id', UUID(), nullable=False),
    sa.Column('requested', DateTime(), nullable=False),
    sa.Column('workstation_num', sa.Integer(), server_default='0', nullable=False),
    sa.Column('terminal_id', sa.Unicode(), server_default='', nullable=False),
    sa.Column('response', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('error', sa.Unicode(), server_default='', nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_terminal_settlement'))
    )


def downgrade():
    op.drop_table('terminal_settlement')
