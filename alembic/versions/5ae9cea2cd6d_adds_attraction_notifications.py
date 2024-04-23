"""Adds attraction notifications

Revision ID: 5ae9cea2cd6d
Revises: 24f0928d0772
Create Date: 2017-12-24 02:34:54.262671

"""


# revision identifiers, used by Alembic.
revision = '5ae9cea2cd6d'
down_revision = '24f0928d0772'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql import table
from sqlalchemy.types import UUID



try:
    is_sqlite = op.get_context().dialect.name == 'sqlite'
except:
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


attraction_feature_table = table(
    'attraction_feature',
    sa.Column('id', UUID()),
    sa.Column('attraction_id', UUID()),
)


attraction_event_table = table(
    'attraction_event',
    sa.Column('id', UUID()),
    sa.Column('attraction_id', UUID()),
    sa.Column('attraction_feature_id', UUID()),
)


attraction_signup_table = table(
    'attraction_signup',
    sa.Column('id', UUID()),
    sa.Column('attraction_id', UUID()),
    sa.Column('attraction_event_id', UUID()),
    sa.Column('checkin_time', sa.DateTime()),
)


def upgrade():
    if is_sqlite:
        with op.batch_alter_table('attendee', reflect_kwargs=sqlite_reflect_kwargs) as batch_op:
            batch_op.add_column(sa.Column('attractions_opt_out', sa.Boolean(), server_default='False', nullable=False))
            batch_op.add_column(sa.Column('notification_pref', sa.Integer(), server_default='0', nullable=False))

        with op.batch_alter_table('attraction_event', reflect_kwargs=sqlite_reflect_kwargs) as batch_op:
            batch_op.add_column(sa.Column('attraction_id', UUID(), nullable=True))

        with op.batch_alter_table('attraction_signup', reflect_kwargs=sqlite_reflect_kwargs) as batch_op:
            batch_op.add_column(sa.Column('attraction_id', UUID(), nullable=True))
    else:
        op.add_column('attendee', sa.Column('attractions_opt_out', sa.Boolean(), server_default='False', nullable=False))
        op.add_column('attendee', sa.Column('notification_pref', sa.Integer(), server_default='0', nullable=False))

        op.add_column('attraction_event', sa.Column('attraction_id', UUID(), nullable=True))

        op.add_column('attraction_signup', sa.Column('attraction_id', UUID(), nullable=True))

        # SQLite does not support UPDATE FROM so skip migrating data for SQLite
        connection = op.get_bind()
        connection.execute(
            attraction_event_table.update().where(
                attraction_event_table.c.attraction_feature_id == attraction_feature_table.c.id
            ).values(
                attraction_id=attraction_feature_table.c.attraction_id
            )
        )

        connection.execute(
            attraction_signup_table.update().where(
                attraction_signup_table.c.attraction_event_id == attraction_event_table.c.id
            ).values(
                attraction_id=attraction_event_table.c.attraction_id
            )
        )

        connection.execute(
            attraction_signup_table.update().where(
                attraction_signup_table.c.checkin_time == None
            ).values(
                checkin_time=text("timezone('utc', '0001-01-01 00:00')")
            )
        )

    if is_sqlite:
        with op.batch_alter_table('attraction_event', reflect_kwargs=sqlite_reflect_kwargs) as batch_op:
            batch_op.alter_column('attraction_id', nullable=False)
            batch_op.create_foreign_key(op.f('fk_attraction_event_attraction_id_attraction'), 'attraction', ['attraction_id'], ['id'])
            batch_op.create_index(op.f('ix_attraction_event_attraction_id'), ['attraction_id'], unique=False)

        with op.batch_alter_table('attraction_signup', reflect_kwargs=sqlite_reflect_kwargs) as batch_op:
            batch_op.alter_column('attraction_id', nullable=False)
            batch_op.create_foreign_key(op.f('fk_attraction_signup_attraction_id_attraction'), 'attraction', ['attraction_id'], ['id'])
            batch_op.alter_column('checkin_time', existing_type=DateTime(), nullable=False)
            batch_op.alter_column('signup_time', existing_type=DateTime(), server_default=None)
            batch_op.create_index(op.f('ix_attraction_signup_checkin_time'), ['checkin_time'], unique=False)

        with op.batch_alter_table('attraction', reflect_kwargs=sqlite_reflect_kwargs) as batch_op:
            batch_op.alter_column('required_checkin', new_column_name='advance_checkin')
            batch_op.alter_column('notifications', new_column_name='advance_notices')
    else:
        op.alter_column('attraction_event', 'attraction_id', nullable=False)
        op.create_foreign_key(op.f('fk_attraction_event_attraction_id_attraction'), 'attraction_event', 'attraction', ['attraction_id'], ['id'])
        op.create_index(op.f('ix_attraction_event_attraction_id'), 'attraction_event', ['attraction_id'], unique=False)

        op.alter_column('attraction_signup', 'attraction_id', nullable=False)
        op.create_foreign_key(op.f('fk_attraction_signup_attraction_id_attraction'), 'attraction_signup', 'attraction', ['attraction_id'], ['id'])
        op.alter_column('attraction_signup', 'checkin_time', existing_type=DateTime(), nullable=False)
        op.alter_column('attraction_signup', 'signup_time', existing_type=DateTime(), server_default=None)
        op.create_index(op.f('ix_attraction_signup_checkin_time'), 'attraction_signup', ['checkin_time'], unique=False)

        op.alter_column('attraction', 'required_checkin', new_column_name='advance_checkin')
        op.alter_column('attraction', 'notifications', new_column_name='advance_notices')


    op.create_table('attraction_notification',
    sa.Column('id', UUID(), nullable=False),
    sa.Column('attraction_event_id', UUID(), nullable=False),
    sa.Column('attraction_id', UUID(), nullable=False),
    sa.Column('attendee_id', UUID(), nullable=False),
    sa.Column('notification_type', sa.Integer(), nullable=False),
    sa.Column('ident', sa.Unicode(), server_default='', nullable=False),
    sa.Column('sid', sa.Unicode(), server_default='', nullable=False),
    sa.Column('sent_time', DateTime(), nullable=False),
    sa.Column('subject', sa.Unicode(), server_default='', nullable=False),
    sa.Column('body', sa.Unicode(), server_default='', nullable=False),
    sa.ForeignKeyConstraint(['attendee_id'], ['attendee.id'], name=op.f('fk_attraction_notification_attendee_id_attendee')),
    sa.ForeignKeyConstraint(['attraction_event_id'], ['attraction_event.id'], name=op.f('fk_attraction_notification_attraction_event_id_attraction_event')),
    sa.ForeignKeyConstraint(['attraction_id'], ['attraction.id'], name=op.f('fk_attraction_notification_attraction_id_attraction')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_attraction_notification'))
    )
    op.create_index(op.f('ix_attraction_notification_ident'), 'attraction_notification', ['ident'], unique=False)

    op.create_table('attraction_notification_reply',
    sa.Column('id', UUID(), nullable=False),
    sa.Column('attraction_event_id', UUID(), nullable=True),
    sa.Column('attraction_id', UUID(), nullable=True),
    sa.Column('attendee_id', UUID(), nullable=True),
    sa.Column('notification_type', sa.Integer(), nullable=False),
    sa.Column('from_phonenumber', sa.Unicode(), server_default='', nullable=False),
    sa.Column('to_phonenumber', sa.Unicode(), server_default='', nullable=False),
    sa.Column('sid', sa.Unicode(), server_default='', nullable=False),
    sa.Column('received_time', DateTime(), nullable=False),
    sa.Column('sent_time', DateTime(), nullable=False),
    sa.Column('body', sa.Unicode(), server_default='', nullable=False),
    sa.ForeignKeyConstraint(['attendee_id'], ['attendee.id'], name=op.f('fk_attraction_notification_reply_attendee_id_attendee')),
    sa.ForeignKeyConstraint(['attraction_event_id'], ['attraction_event.id'], name=op.f('fk_attraction_notification_reply_attraction_event_id_attraction_event')),
    sa.ForeignKeyConstraint(['attraction_id'], ['attraction.id'], name=op.f('fk_attraction_notification_reply_attraction_id_attraction')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_attraction_notification_reply'))
    )
    op.create_index(op.f('ix_attraction_notification_reply_sid'), 'attraction_notification_reply', ['sid'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_attraction_notification_reply_sid'), table_name='attraction_notification_reply')
    op.drop_table('attraction_notification_reply')
    op.drop_index(op.f('ix_attraction_notification_ident'), table_name='attraction_notification')
    op.drop_table('attraction_notification')

    op.drop_index(op.f('ix_attraction_signup_checkin_time'), table_name='attraction_signup')
    op.drop_index(op.f('ix_attraction_event_attraction_id'), table_name='attraction_event')

    op.alter_column('attraction', 'advance_checkin', new_column_name='required_checkin')
    op.alter_column('attraction', 'advance_notices', new_column_name='notifications')
    op.alter_column('attraction_signup', 'signup_time', existing_type=DateTime(), server_default=text(utcnow_server_default))
    op.alter_column('attraction_signup', 'checkin_time', existing_type=DateTime(), nullable=True)

    op.drop_constraint(op.f('fk_attraction_signup_attraction_id_attraction'), 'attraction_signup', type_='foreignkey')
    op.drop_constraint(op.f('fk_attraction_event_attraction_id_attraction'), 'attraction_event', type_='foreignkey')

    op.drop_column('attraction_signup', 'attraction_id')
    op.drop_column('attraction_event', 'attraction_id')

    op.drop_column('attendee', 'notification_pref')
    op.drop_column('attendee', 'attractions_opt_out')
