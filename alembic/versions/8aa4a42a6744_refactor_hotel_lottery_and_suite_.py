"""Refactor hotel lottery and suite lottery forms

Revision ID: 8aa4a42a6744
Revises: 2e9e8e65e89c
Create Date: 2024-09-23 21:00:45.880362

"""


# revision identifiers, used by Alembic.
revision = '8aa4a42a6744'
down_revision = '2e9e8e65e89c'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import Sequence, CreateSequence, DropSequence
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
    op.execute(CreateSequence(Sequence('lottery_application_response_id_seq')))
    op.add_column('lottery_application', sa.Column('response_id', sa.Integer(), server_default=sa.text("nextval('lottery_application_response_id_seq')"), nullable=False))
    op.create_unique_constraint(op.f('uq_lottery_application_response_id'), 'lottery_application', ['response_id'])
    op.add_column('lottery_application', sa.Column('confirmation_num', sa.Unicode(), server_default='', nullable=False))
    op.add_column('lottery_application', sa.Column('status', sa.Integer(), server_default='12956888', nullable=False))
    op.add_column('lottery_application', sa.Column('entry_started', residue.UTCDateTime(), nullable=True))
    op.add_column('lottery_application', sa.Column('entry_metadata', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False))
    op.add_column('lottery_application', sa.Column('entry_type', sa.Integer(), nullable=True))
    op.add_column('lottery_application', sa.Column('current_step', sa.Integer(), server_default='0', nullable=False))
    op.add_column('lottery_application', sa.Column('last_submitted', residue.UTCDateTime(), nullable=True))
    op.add_column('lottery_application', sa.Column('admin_notes', sa.Unicode(), server_default='', nullable=False))
    op.add_column('lottery_application', sa.Column('earliest_checkin_date', sa.Date(), nullable=True))
    op.add_column('lottery_application', sa.Column('latest_checkin_date', sa.Date(), nullable=True))
    op.add_column('lottery_application', sa.Column('earliest_checkout_date', sa.Date(), nullable=True))
    op.add_column('lottery_application', sa.Column('latest_checkout_date', sa.Date(), nullable=True))
    op.add_column('lottery_application', sa.Column('selection_priorities', sa.Unicode(), server_default='', nullable=False))
    op.add_column('lottery_application', sa.Column('room_opt_out', sa.Boolean(), server_default='False', nullable=False))
    op.drop_column('lottery_application', 'room_selection_priorities')
    op.drop_column('lottery_application', 'latest_room_checkout_date')
    op.drop_column('lottery_application', 'earliest_suite_checkin_date')
    op.drop_column('lottery_application', 'earliest_room_checkin_date')
    op.drop_column('lottery_application', 'room_step')
    op.drop_column('lottery_application', 'earliest_suite_checkout_date')
    op.drop_column('lottery_application', 'suite_selection_priorities')
    op.drop_column('lottery_application', 'latest_room_checkin_date')
    op.drop_column('lottery_application', 'earliest_room_checkout_date')
    op.drop_column('lottery_application', 'wants_suite')
    op.drop_column('lottery_application', 'latest_suite_checkout_date')
    op.drop_column('lottery_application', 'wants_room')
    op.drop_column('lottery_application', 'latest_suite_checkin_date')
    op.drop_column('lottery_application', 'suite_step')


def downgrade():
    op.add_column('lottery_application', sa.Column('suite_step', sa.INTEGER(), server_default=sa.text('0'), autoincrement=False, nullable=False))
    op.add_column('lottery_application', sa.Column('latest_suite_checkin_date', sa.DATE(), autoincrement=False, nullable=True))
    op.add_column('lottery_application', sa.Column('wants_room', sa.BOOLEAN(), server_default=sa.text('false'), autoincrement=False, nullable=False))
    op.add_column('lottery_application', sa.Column('latest_suite_checkout_date', sa.DATE(), autoincrement=False, nullable=True))
    op.add_column('lottery_application', sa.Column('wants_suite', sa.BOOLEAN(), server_default=sa.text('false'), autoincrement=False, nullable=False))
    op.add_column('lottery_application', sa.Column('earliest_room_checkout_date', sa.DATE(), autoincrement=False, nullable=True))
    op.add_column('lottery_application', sa.Column('latest_room_checkin_date', sa.DATE(), autoincrement=False, nullable=True))
    op.add_column('lottery_application', sa.Column('suite_selection_priorities', sa.VARCHAR(), server_default=sa.text("''::character varying"), autoincrement=False, nullable=False))
    op.add_column('lottery_application', sa.Column('earliest_suite_checkout_date', sa.DATE(), autoincrement=False, nullable=True))
    op.add_column('lottery_application', sa.Column('room_step', sa.INTEGER(), server_default=sa.text('0'), autoincrement=False, nullable=False))
    op.add_column('lottery_application', sa.Column('earliest_room_checkin_date', sa.DATE(), autoincrement=False, nullable=True))
    op.add_column('lottery_application', sa.Column('earliest_suite_checkin_date', sa.DATE(), autoincrement=False, nullable=True))
    op.add_column('lottery_application', sa.Column('latest_room_checkout_date', sa.DATE(), autoincrement=False, nullable=True))
    op.add_column('lottery_application', sa.Column('room_selection_priorities', sa.VARCHAR(), server_default=sa.text("''::character varying"), autoincrement=False, nullable=False))
    op.drop_constraint(op.f('uq_lottery_application_response_id'), 'lottery_application', type_='unique')
    op.drop_column('lottery_application', 'room_opt_out')
    op.drop_column('lottery_application', 'selection_priorities')
    op.drop_column('lottery_application', 'latest_checkout_date')
    op.drop_column('lottery_application', 'earliest_checkout_date')
    op.drop_column('lottery_application', 'latest_checkin_date')
    op.drop_column('lottery_application', 'earliest_checkin_date')
    op.drop_column('lottery_application', 'admin_notes')
    op.drop_column('lottery_application', 'last_submitted')
    op.drop_column('lottery_application', 'current_step')
    op.drop_column('lottery_application', 'entry_type')
    op.drop_column('lottery_application', 'entry_metadata')
    op.drop_column('lottery_application', 'entry_started')
    op.drop_column('lottery_application', 'status')
    op.drop_column('lottery_application', 'response_id')
    op.drop_column('lottery_application', 'confirmation_num')
    op.execute(DropSequence(Sequence('lottery_application_response_id_seq')))
