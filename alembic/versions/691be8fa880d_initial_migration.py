"""Initial migration

Revision ID: 691be8fa880d
Revises: 416eb615ff1a
Create Date: 2017-04-24 09:40:57.929468

"""


# revision identifiers, used by Alembic.
revision = '691be8fa880d'
down_revision = '416eb615ff1a'
branch_labels = ('tabletop',)
depends_on = None

from alembic import op
import sqlalchemy as sa
import sideboard.lib.sa


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
    op.create_table('tabletop_tournament',
    sa.Column('id', sideboard.lib.sa.UUID(), nullable=False),
    sa.Column('event_id', sideboard.lib.sa.UUID(), nullable=False),
    sa.Column('name', sa.Unicode(), server_default='', nullable=False),
    sa.ForeignKeyConstraint(['event_id'], ['event.id'], name=op.f('fk_tabletop_tournament_event_id_event')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_tabletop_tournament')),
    sa.UniqueConstraint('event_id', name=op.f('uq_tabletop_tournament_event_id'))
    )
    op.create_table('tabletop_entrant',
    sa.Column('id', sideboard.lib.sa.UUID(), nullable=False),
    sa.Column('tournament_id', sideboard.lib.sa.UUID(), nullable=False),
    sa.Column('attendee_id', sideboard.lib.sa.UUID(), nullable=False),
    sa.Column('signed_up', sideboard.lib.sa.UTCDateTime(), nullable=False),
    sa.Column('confirmed', sa.Boolean(), server_default='False', nullable=False),
    sa.ForeignKeyConstraint(['attendee_id'], ['attendee.id'], name=op.f('fk_tabletop_entrant_attendee_id_attendee')),
    sa.ForeignKeyConstraint(['tournament_id'], ['tabletop_tournament.id'], name=op.f('fk_tabletop_entrant_tournament_id_tabletop_tournament')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_tabletop_entrant')),
    sa.UniqueConstraint('tournament_id', 'attendee_id', name='_tournament_entrant_uniq')
    )
    op.create_table('tabletop_game',
    sa.Column('id', sideboard.lib.sa.UUID(), nullable=False),
    sa.Column('code', sa.Unicode(), server_default='', nullable=False),
    sa.Column('name', sa.Unicode(), server_default='', nullable=False),
    sa.Column('attendee_id', sideboard.lib.sa.UUID(), nullable=False),
    sa.Column('returned', sa.Boolean(), server_default='False', nullable=False),
    sa.ForeignKeyConstraint(['attendee_id'], ['attendee.id'], name=op.f('fk_tabletop_game_attendee_id_attendee')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_tabletop_game'))
    )
    op.create_table('tabletop_checkout',
    sa.Column('id', sideboard.lib.sa.UUID(), nullable=False),
    sa.Column('game_id', sideboard.lib.sa.UUID(), nullable=False),
    sa.Column('attendee_id', sideboard.lib.sa.UUID(), nullable=False),
    sa.Column('checked_out', sideboard.lib.sa.UTCDateTime(), nullable=False),
    sa.Column('returned', sideboard.lib.sa.UTCDateTime(), nullable=True),
    sa.ForeignKeyConstraint(['attendee_id'], ['attendee.id'], name=op.f('fk_tabletop_checkout_attendee_id_attendee')),
    sa.ForeignKeyConstraint(['game_id'], ['tabletop_game.id'], name=op.f('fk_tabletop_checkout_game_id_tabletop_game')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_tabletop_checkout'))
    )
    op.create_table('tabletop_sms_reminder',
    sa.Column('id', sideboard.lib.sa.UUID(), nullable=False),
    sa.Column('entrant_id', sideboard.lib.sa.UUID(), nullable=False),
    sa.Column('sid', sa.Unicode(), server_default='', nullable=False),
    sa.Column('when', sideboard.lib.sa.UTCDateTime(), nullable=False),
    sa.Column('text', sa.Unicode(), server_default='', nullable=False),
    sa.ForeignKeyConstraint(['entrant_id'], ['tabletop_entrant.id'], name=op.f('fk_tabletop_sms_reminder_entrant_id_tabletop_entrant')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_tabletop_sms_reminder')),
    sa.UniqueConstraint('entrant_id', name=op.f('uq_tabletop_sms_reminder_entrant_id'))
    )
    op.create_table('tabletop_sms_reply',
    sa.Column('id', sideboard.lib.sa.UUID(), nullable=False),
    sa.Column('entrant_id', sideboard.lib.sa.UUID(), nullable=True),
    sa.Column('sid', sa.Unicode(), server_default='', nullable=False),
    sa.Column('when', sideboard.lib.sa.UTCDateTime(), nullable=False),
    sa.Column('text', sa.Unicode(), server_default='', nullable=False),
    sa.ForeignKeyConstraint(['entrant_id'], ['tabletop_entrant.id'], name=op.f('fk_tabletop_sms_reply_entrant_id_tabletop_entrant')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_tabletop_sms_reply'))
    )


def downgrade():
    op.drop_table('tabletop_sms_reply')
    op.drop_table('tabletop_sms_reminder')
    op.drop_table('tabletop_checkout')
    op.drop_table('tabletop_game')
    op.drop_table('tabletop_entrant')
    op.drop_table('tabletop_tournament')
