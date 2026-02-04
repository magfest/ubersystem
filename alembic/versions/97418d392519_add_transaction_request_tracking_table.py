"""Add transaction request tracking table

Revision ID: 97418d392519
Revises: 49e309c12e97
Create Date: 2023-11-08 20:04:52.547736

"""


# revision identifiers, used by Alembic.
revision = '97418d392519'
down_revision = '49e309c12e97'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import Sequence, CreateSequence, DropSequence


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
    op.execute(CreateSequence(Sequence('txn_request_tracking_incr_id_seq')))
    op.create_table('txn_request_tracking',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('incr_id', sa.Integer(), server_default=sa.text("nextval('txn_request_tracking_incr_id_seq')"), nullable=False, unique=True),
    sa.Column('workstation_num', sa.Integer(), server_default='0', nullable=False),
    sa.Column('terminal_id', sa.Unicode(), server_default='', nullable=False),
    sa.Column('who', sa.Unicode(), server_default='', nullable=False),
    sa.Column('requested', sa.DateTime(timezone=True), server_default=sa.text("timezone('utc', current_timestamp)"), nullable=False),
    sa.Column('resolved', sa.DateTime(timezone=True), nullable=True),
    sa.Column('success', sa.Boolean(), server_default='False', nullable=False),
    sa.Column('response', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('internal_error', sa.Unicode(), server_default='', nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_txn_request_tracking'))
    )


def downgrade():
    op.drop_table('txn_request_tracking')
    op.execute(DropSequence(Sequence('txn_request_tracking_incr_id_seq')))
