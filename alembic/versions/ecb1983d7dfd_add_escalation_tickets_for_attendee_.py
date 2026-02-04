"""Add escalation tickets for attendee check-in

Revision ID: ecb1983d7dfd
Revises: 8224640bc6cc
Create Date: 2024-11-15 22:59:42.134196

"""


# revision identifiers, used by Alembic.
revision = 'ecb1983d7dfd'
down_revision = '8224640bc6cc'
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
    op.execute(CreateSequence(Sequence('escalation_ticket_ticket_id_seq')))
    op.create_table('escalation_ticket',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('created', sa.DateTime(timezone=True), server_default=sa.text("timezone('utc', current_timestamp)"), nullable=False),
    sa.Column('last_updated', sa.DateTime(timezone=True), server_default=sa.text("timezone('utc', current_timestamp)"), nullable=False),
    sa.Column('external_id', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('last_synced', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('ticket_id', sa.Integer(), server_default=sa.text("nextval('escalation_ticket_ticket_id_seq')"), nullable=False),
    sa.Column('description', sa.Unicode(), server_default='', nullable=False),
    sa.Column('admin_notes', sa.Unicode(), server_default='', nullable=False),
    sa.Column('resolved', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_escalation_ticket')),
    sa.UniqueConstraint('ticket_id', name=op.f('uq_escalation_ticket_ticket_id'))
    )
    op.create_table('attendee_escalation_ticket',
    sa.Column('attendee_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('escalation_ticket_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.ForeignKeyConstraint(['attendee_id'], ['attendee.id'], name=op.f('fk_attendee_escalation_ticket_attendee_id_attendee')),
    sa.ForeignKeyConstraint(['escalation_ticket_id'], ['escalation_ticket.id'], name=op.f('fk_attendee_escalation_ticket_escalation_ticket_id_escalation_ticket')),
    sa.UniqueConstraint('attendee_id', 'escalation_ticket_id', name=op.f('uq_attendee_escalation_ticket_attendee_id'))
    )
    op.create_index('ix_attendee_escalation_ticket_attendee_id', 'attendee_escalation_ticket', ['attendee_id'], unique=False)
    op.create_index('ix_attendee_escalation_ticket_escalation_ticket_id', 'attendee_escalation_ticket', ['escalation_ticket_id'], unique=False)


def downgrade():
    op.drop_index('ix_attendee_escalation_ticket_escalation_ticket_id', table_name='attendee_escalation_ticket')
    op.drop_index('ix_attendee_escalation_ticket_attendee_id', table_name='attendee_escalation_ticket')
    op.drop_table('attendee_escalation_ticket')
    op.drop_table('escalation_ticket')
    op.execute(DropSequence(Sequence('escalation_ticket_ticket_id_seq')))
