"""Initial migration

Revision ID: 416eb615ff1a
Revises: 1ed43776064f
Create Date: 2017-04-23 19:07:31.868613

"""


# revision identifiers, used by Alembic.
revision = '416eb615ff1a'
down_revision = '1ed43776064f'
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


def upgrade():
    op.create_table('event',
    sa.Column('id', residue.UUID(), nullable=False),
    sa.Column('location', sa.Integer(), nullable=False),
    sa.Column('start_time', residue.UTCDateTime(), nullable=False),
    sa.Column('duration', sa.Integer(), nullable=False),
    sa.Column('name', sa.Unicode(), server_default='', nullable=False),
    sa.Column('description', sa.Unicode(), server_default='', nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_event'))
    )
    op.create_table('assigned_panelist',
    sa.Column('id', residue.UUID(), nullable=False),
    sa.Column('attendee_id', residue.UUID(), nullable=False),
    sa.Column('event_id', residue.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['attendee_id'], ['attendee.id'], name=op.f('fk_assigned_panelist_attendee_id_attendee'), ondelete='cascade'),
    sa.ForeignKeyConstraint(['event_id'], ['event.id'], name=op.f('fk_assigned_panelist_event_id_event'), ondelete='cascade'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_assigned_panelist'))
    )
    op.create_table('event_feedback',
    sa.Column('id', residue.UUID(), nullable=False),
    sa.Column('event_id', residue.UUID(), nullable=False),
    sa.Column('attendee_id', residue.UUID(), nullable=False),
    sa.Column('headcount_starting', sa.Integer(), server_default='0', nullable=False),
    sa.Column('headcount_during', sa.Integer(), server_default='0', nullable=False),
    sa.Column('comments', sa.Unicode(), server_default='', nullable=False),
    sa.Column('rating', sa.Integer(), server_default='54944008', nullable=False),
    sa.ForeignKeyConstraint(['attendee_id'], ['attendee.id'], name=op.f('fk_event_feedback_attendee_id_attendee'), ondelete='cascade'),
    sa.ForeignKeyConstraint(['event_id'], ['event.id'], name=op.f('fk_event_feedback_event_id_event')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_event_feedback'))
    )
    op.create_table('panel_application',
    sa.Column('id', residue.UUID(), nullable=False),
    sa.Column('event_id', residue.UUID(), nullable=True),
    sa.Column('poc_id', residue.UUID(), nullable=True),
    sa.Column('name', sa.Unicode(), server_default='', nullable=False),
    sa.Column('length', sa.Unicode(), server_default='', nullable=False),
    sa.Column('description', sa.Unicode(), server_default='', nullable=False),
    sa.Column('unavailable', sa.Unicode(), server_default='', nullable=False),
    sa.Column('affiliations', sa.Unicode(), server_default='', nullable=False),
    sa.Column('past_attendance', sa.Unicode(), server_default='', nullable=False),
    sa.Column('presentation', sa.Integer(), nullable=False),
    sa.Column('other_presentation', sa.Unicode(), server_default='', nullable=False),
    sa.Column('tech_needs', sa.Unicode(), server_default='', nullable=False),
    sa.Column('other_tech_needs', sa.Unicode(), server_default='', nullable=False),
    sa.Column('panelist_bringing', sa.Unicode(), server_default='', nullable=False),
    sa.Column('applied', residue.UTCDateTime(), server_default=sa.text(utcnow_server_default), nullable=False),
    sa.Column('status', sa.Integer(), server_default='196944751', nullable=False),
    sa.Column('comments', sa.Unicode(), server_default='', nullable=False),
    sa.ForeignKeyConstraint(['event_id'], ['event.id'], name=op.f('fk_panel_application_event_id_event'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['poc_id'], ['attendee.id'], name=op.f('fk_panel_application_poc_id_attendee'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_panel_application'))
    )
    op.create_table('panel_applicant',
    sa.Column('id', residue.UUID(), nullable=False),
    sa.Column('app_id', residue.UUID(), nullable=False),
    sa.Column('attendee_id', residue.UUID(), nullable=True),
    sa.Column('submitter', sa.Boolean(), server_default='False', nullable=False),
    sa.Column('first_name', sa.Unicode(), server_default='', nullable=False),
    sa.Column('last_name', sa.Unicode(), server_default='', nullable=False),
    sa.Column('email', sa.Unicode(), server_default='', nullable=False),
    sa.Column('cellphone', sa.Unicode(), server_default='', nullable=False),
    sa.ForeignKeyConstraint(['app_id'], ['panel_application.id'], name=op.f('fk_panel_applicant_app_id_panel_application'), ondelete='cascade'),
    sa.ForeignKeyConstraint(['attendee_id'], ['attendee.id'], name=op.f('fk_panel_applicant_attendee_id_attendee'), ondelete='cascade'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_panel_applicant'))
    )


def downgrade():
    op.drop_table('panel_applicant')
    op.drop_table('panel_application')
    op.drop_table('event_feedback')
    op.drop_table('assigned_panelist')
    op.drop_table('event')
