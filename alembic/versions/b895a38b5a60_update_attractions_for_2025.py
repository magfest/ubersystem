"""Update attractions for 2025

Revision ID: b895a38b5a60
Revises: 417aacb2c6e9
Create Date: 2025-11-13 15:57:43.036822

"""


# revision identifiers, used by Alembic.
revision = 'b895a38b5a60'
down_revision = '417aacb2c6e9'
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
    op.drop_column('attraction', 'advance_notices')
    op.add_column('attraction', sa.Column('checkin_reminder', sa.Integer(), nullable=True))
    op.add_column('attraction', sa.Column('populate_schedule', sa.Boolean(), server_default='True', nullable=False))
    op.add_column('attraction', sa.Column('no_notifications', sa.Boolean(), server_default='False', nullable=False))
    op.add_column('attraction', sa.Column('waitlist_available', sa.Boolean(), server_default='True', nullable=False))
    op.add_column('attraction', sa.Column('waitlist_slots', sa.Integer(), server_default='10', nullable=False))
    op.add_column('attraction', sa.Column('signups_open_relative', sa.Integer(), server_default='0', nullable=False))
    op.add_column('attraction', sa.Column('signups_open_time', residue.UTCDateTime(), nullable=True))
    op.add_column('attraction', sa.Column('slots', sa.Integer(), server_default='1', nullable=False))
    op.add_column('attraction_event', sa.Column('populate_schedule', sa.Boolean(), server_default='True', nullable=False))
    op.add_column('attraction_event', sa.Column('no_notifications', sa.Boolean(), server_default='False', nullable=False))
    op.add_column('attraction_event', sa.Column('waitlist_available', sa.Boolean(), server_default='True', nullable=False))
    op.add_column('attraction_event', sa.Column('waitlist_slots', sa.Integer(), server_default='10', nullable=False))
    op.add_column('attraction_event', sa.Column('signups_open_relative', sa.Integer(), server_default='0', nullable=False))
    op.add_column('attraction_event', sa.Column('signups_open_time', residue.UTCDateTime(), nullable=True))
    op.add_column('attraction_event', sa.Column('event_location_id', residue.UUID(), nullable=True))
    op.create_foreign_key(op.f('fk_attraction_event_location_id_event_location'), 'attraction_event', 'event_location', ['event_location_id'], ['id'], ondelete='SET NULL')
    op.drop_column('attraction_event', 'signups_open')
    op.drop_column('attraction_event', 'location')
    op.add_column('attraction_signup', sa.Column('on_waitlist', sa.Boolean(), server_default='True', nullable=False))
    op.add_column('attraction_feature', sa.Column('populate_schedule', sa.Boolean(), server_default='True', nullable=False))
    op.add_column('attraction_feature', sa.Column('no_notifications', sa.Boolean(), server_default='False', nullable=False))
    op.add_column('attraction_feature', sa.Column('waitlist_available', sa.Boolean(), server_default='True', nullable=False))
    op.add_column('attraction_feature', sa.Column('waitlist_slots', sa.Integer(), server_default='10', nullable=False))
    op.add_column('attraction_feature', sa.Column('signups_open_relative', sa.Integer(), server_default='0', nullable=False))
    op.add_column('attraction_feature', sa.Column('signups_open_time', residue.UTCDateTime(), nullable=True))
    op.add_column('attraction_feature', sa.Column('slots', sa.Integer(), server_default='1', nullable=False))
    op.add_column('event', sa.Column('attraction_event_id', residue.UUID(), nullable=True))
    op.create_foreign_key(op.f('fk_event_attraction_event_id_attraction_event'), 'event', 'attraction_event', ['attraction_event_id'], ['id'], ondelete='SET NULL')


def downgrade():
    op.drop_constraint(op.f('fk_event_attraction_event_id_attraction_event'), 'event', type_='foreignkey')
    op.drop_column('event', 'attraction_event_id')
    op.drop_column('attraction_feature', 'slots')
    op.drop_column('attraction_feature', 'signups_open_time')
    op.drop_column('attraction_feature', 'signups_open_relative')
    op.drop_column('attraction_feature', 'waitlist_slots')
    op.drop_column('attraction_feature', 'waitlist_available')
    op.drop_column('attraction_feature', 'no_notifications')
    op.drop_column('attraction_feature', 'populate_schedule')
    op.add_column('attraction_event', sa.Column('location', sa.INTEGER(), autoincrement=False, nullable=False))
    op.add_column('attraction_event', sa.Column('signups_open', sa.BOOLEAN(), server_default=sa.text('true'), autoincrement=False, nullable=False))
    op.drop_constraint(op.f('fk_attraction_event_location_id_event_location'), 'attraction_event', type_='foreignkey')
    op.drop_column('attraction_event', 'event_location_id')
    op.drop_column('attraction_event', 'signups_open_time')
    op.drop_column('attraction_event', 'signups_open_relative')
    op.drop_column('attraction_event', 'waitlist_slots')
    op.drop_column('attraction_event', 'waitlist_available')
    op.drop_column('attraction_event', 'no_notifications')
    op.drop_column('attraction_event', 'populate_schedule')
    op.drop_column('attraction_signup', 'on_waitlist')
    op.drop_column('attraction', 'slots')
    op.drop_column('attraction', 'signups_open_time')
    op.drop_column('attraction', 'signups_open_relative')
    op.drop_column('attraction', 'waitlist_slots')
    op.drop_column('attraction', 'waitlist_available')
    op.drop_column('attraction', 'no_notifications')
    op.drop_column('attraction', 'populate_schedule')
    op.drop_column('attraction', 'checkin_reminder')
    op.add_column('attraction', sa.Column('advance_notices', residue.JSON(), server_default='[]', nullable=False))
