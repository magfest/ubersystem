"""Remove tabletop tournament tables

Revision ID: f30b7120de0b
Revises: 9168e926974e
Create Date: 2024-03-23 22:40:20.302728

"""


# revision identifiers, used by Alembic.
revision = 'f30b7120de0b'
down_revision = '9168e926974e'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


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
    op.drop_table('tabletop_sms_reminder')
    op.drop_table('tabletop_sms_reply')
    op.drop_table('tabletop_entrant')
    op.drop_table('tabletop_tournament')


def downgrade():
    op.create_table('tabletop_sms_reminder',
    sa.Column('id', postgresql.UUID(), autoincrement=False, nullable=False),
    sa.Column('entrant_id', postgresql.UUID(), autoincrement=False, nullable=False),
    sa.Column('sid', sa.VARCHAR(), server_default=sa.text("''::character varying"), autoincrement=False, nullable=False),
    sa.Column('when', postgresql.TIMESTAMP(), autoincrement=False, nullable=False),
    sa.Column('text', sa.VARCHAR(), server_default=sa.text("''::character varying"), autoincrement=False, nullable=False),
    sa.ForeignKeyConstraint(['entrant_id'], ['tabletop_entrant.id'], name='fk_tabletop_sms_reminder_entrant_id_tabletop_entrant'),
    sa.PrimaryKeyConstraint('id', name='pk_tabletop_sms_reminder'),
    sa.UniqueConstraint('entrant_id', name='uq_tabletop_sms_reminder_entrant_id')
    )
    op.create_table('tabletop_sms_reply',
    sa.Column('id', postgresql.UUID(), autoincrement=False, nullable=False),
    sa.Column('entrant_id', postgresql.UUID(), autoincrement=False, nullable=True),
    sa.Column('sid', sa.VARCHAR(), server_default=sa.text("''::character varying"), autoincrement=False, nullable=False),
    sa.Column('when', postgresql.TIMESTAMP(), autoincrement=False, nullable=False),
    sa.Column('text', sa.VARCHAR(), server_default=sa.text("''::character varying"), autoincrement=False, nullable=False),
    sa.ForeignKeyConstraint(['entrant_id'], ['tabletop_entrant.id'], name='fk_tabletop_sms_reply_entrant_id_tabletop_entrant'),
    sa.PrimaryKeyConstraint('id', name='pk_tabletop_sms_reply')
    )
    op.create_table('tabletop_entrant',
    sa.Column('id', postgresql.UUID(), autoincrement=False, nullable=False),
    sa.Column('tournament_id', postgresql.UUID(), autoincrement=False, nullable=False),
    sa.Column('attendee_id', postgresql.UUID(), autoincrement=False, nullable=False),
    sa.Column('signed_up', postgresql.TIMESTAMP(), autoincrement=False, nullable=False),
    sa.Column('confirmed', sa.BOOLEAN(), server_default=sa.text('false'), autoincrement=False, nullable=False),
    sa.ForeignKeyConstraint(['attendee_id'], ['attendee.id'], name='fk_tabletop_entrant_attendee_id_attendee'),
    sa.ForeignKeyConstraint(['tournament_id'], ['tabletop_tournament.id'], name='fk_tabletop_entrant_tournament_id_tabletop_tournament'),
    sa.PrimaryKeyConstraint('id', name='pk_tabletop_entrant'),
    sa.UniqueConstraint('tournament_id', 'attendee_id', name='_tournament_entrant_uniq'),
    postgresql_ignore_search_path=False
    )
    op.create_table('tabletop_tournament',
    sa.Column('id', postgresql.UUID(), autoincrement=False, nullable=False),
    sa.Column('event_id', postgresql.UUID(), autoincrement=False, nullable=False),
    sa.Column('name', sa.VARCHAR(), server_default=sa.text("''::character varying"), autoincrement=False, nullable=False),
    sa.ForeignKeyConstraint(['event_id'], ['event.id'], name='fk_tabletop_tournament_event_id_event'),
    sa.PrimaryKeyConstraint('id', name='pk_tabletop_tournament'),
    sa.UniqueConstraint('event_id', name='uq_tabletop_tournament_event_id')
    )
