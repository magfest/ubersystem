"""Adds Attractions

Revision ID: 76e2905cff66
Revises: 06b9ad98e471
Create Date: 2017-11-23 04:34:38.474631

"""


# revision identifiers, used by Alembic.
revision = '76e2905cff66'
down_revision = '06b9ad98e471'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa
import residue


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


def upgrade():
    op.create_table('attraction',
    sa.Column('id', residue.UUID(), nullable=False),
    sa.Column('name', sa.Unicode(), server_default='', nullable=False, unique=True),
    sa.Column('description', sa.Unicode(), server_default='', nullable=False),
    sa.Column('notifications', residue.JSON(), server_default='[]', nullable=False),
    sa.Column('required_checkin', sa.Integer(), server_default='0', nullable=False),
    sa.Column('restriction', sa.Integer(), server_default='0', nullable=False),
    sa.Column('department_id', residue.UUID(), nullable=True),
    sa.Column('owner_id', residue.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['department_id'], ['department.id'], name=op.f('fk_attraction_department_id_department')),
    sa.ForeignKeyConstraint(['owner_id'], ['admin_account.id'], name=op.f('fk_attraction_owner_id_admin_account')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_attraction')),
    )
    op.create_table('attraction_feature',
    sa.Column('id', residue.UUID(), nullable=False),
    sa.Column('name', sa.Unicode(), server_default='', nullable=False),
    sa.Column('description', sa.Unicode(), server_default='', nullable=False),
    sa.Column('attraction_id', residue.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['attraction_id'], ['attraction.id'], name=op.f('fk_attraction_feature_attraction_id_attraction')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_attraction_feature')),
    sa.UniqueConstraint('name', 'attraction_id'),
    )
    op.create_table('attraction_event',
    sa.Column('id', residue.UUID(), nullable=False),
    sa.Column('attraction_feature_id', residue.UUID(), nullable=False),
    sa.Column('location', sa.Integer(), nullable=False),
    sa.Column('start_time', residue.UTCDateTime(), nullable=False),
    sa.Column('duration', sa.Integer(), server_default='900', nullable=False),
    sa.Column('slots', sa.Integer(), server_default='1', nullable=False),
    sa.ForeignKeyConstraint(['attraction_feature_id'], ['attraction_feature.id'], name=op.f('fk_attraction_event_attraction_feature_id_attraction_feature')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_attraction_event')),
    )
    op.create_table('attraction_signup',
    sa.Column('id', residue.UUID(), nullable=False),
    sa.Column('attraction_event_id', residue.UUID(), nullable=False),
    sa.Column('attendee_id', residue.UUID(), nullable=False),
    sa.Column('signup_time', residue.UTCDateTime(), server_default=sa.text(utcnow_server_default), nullable=False),
    sa.Column('checkin_time', residue.UTCDateTime(), nullable=True),
    sa.ForeignKeyConstraint(['attendee_id'], ['attendee.id'], name=op.f('fk_attraction_signup_attendee_id_attendee')),
    sa.ForeignKeyConstraint(['attraction_event_id'], ['attraction_event.id'], name=op.f('fk_attraction_signup_attraction_event_id_attraction_event')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_attraction_signup')),
    sa.UniqueConstraint('attraction_event_id', 'attendee_id', name=op.f('uq_attraction_signup_attraction_event_id'))
    )


def downgrade():
    op.drop_table('attraction_signup')
    op.drop_table('attraction_event')
    op.drop_table('attraction_feature')
    op.drop_table('attraction')
