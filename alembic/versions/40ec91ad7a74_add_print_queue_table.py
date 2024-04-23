"""Add print queue table

Revision ID: 40ec91ad7a74
Revises: cc0f9e9861cd
Create Date: 2021-11-04 03:38:08.816882

"""


# revision identifiers, used by Alembic.
revision = '40ec91ad7a74'
down_revision = 'cc0f9e9861cd'
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
    op.create_table('print_job',
    sa.Column('id', UUID(), nullable=False),
    sa.Column('attendee_id', UUID(), nullable=False),
    sa.Column('admin_id', UUID(), nullable=False),
    sa.Column('admin_name', sa.Unicode(), server_default='', nullable=False),
    sa.Column('printer_id', sa.Unicode(), server_default='', nullable=False),
    sa.Column('reg_station', sa.Integer(), nullable=True),
    sa.Column('queued', DateTime(), nullable=True),
    sa.Column('printed', DateTime(), nullable=True),
    sa.Column('errors', sa.Unicode(), server_default='', nullable=False),
    sa.Column('is_minor', sa.Boolean(), nullable=False),
    sa.Column('json_data', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.ForeignKeyConstraint(['admin_id'], ['admin_account.id'], name=op.f('fk_print_queue_admin_id_admin_account')),
    sa.ForeignKeyConstraint(['attendee_id'], ['attendee.id'], name=op.f('fk_print_queue_attendee_id_attendee')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_print_queue'))
    )


def downgrade():
    op.drop_table('print_job')
