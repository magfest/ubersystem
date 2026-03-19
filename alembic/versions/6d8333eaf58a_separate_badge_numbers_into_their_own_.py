"""Separate badge numbers into their own table

Revision ID: 6d8333eaf58a
Revises: b36e0ca2ac50
Create Date: 2025-04-04 09:00:54.335351

"""


# revision identifiers, used by Alembic.
revision = '6d8333eaf58a'
down_revision = 'b36e0ca2ac50'
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
    op.create_table('badge_info',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('created', sa.DateTime(timezone=True), server_default=sa.text("timezone('utc', current_timestamp)"), nullable=False),
    sa.Column('last_updated', sa.DateTime(timezone=True), server_default=sa.text("timezone('utc', current_timestamp)"), nullable=False),
    sa.Column('external_id', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('last_synced', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('attendee_id', sa.Uuid(as_uuid=False), nullable=True),
    sa.Column('active', sa.Boolean(), server_default='False', nullable=False),
    sa.Column('picked_up', sa.DateTime(timezone=True), nullable=True),
    sa.Column('reported_lost', sa.DateTime(timezone=True), nullable=True),
    sa.Column('ident', sa.Integer(), server_default='0', nullable=False),
    sa.ForeignKeyConstraint(['attendee_id'], ['attendee.id'], name=op.f('fk_badge_info_attendee_id_attendee'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_badge_info'))
    )
    op.create_index('ix_badge_info_attendee_id', 'badge_info', [sa.text('attendee_id DESC')], unique=False)
    op.create_index(op.f('ix_badge_info_ident'), 'badge_info', ['ident'], unique=False)
    op.drop_constraint('uq_attendee_badge_num', 'attendee', type_='unique')
    op.drop_column('attendee', 'badge_num')


def downgrade():
    op.add_column('attendee', sa.Column('badge_num', sa.INTEGER(), autoincrement=False, nullable=True))
    op.create_unique_constraint('uq_attendee_badge_num', 'attendee', ['badge_num'])
    op.drop_index(op.f('ix_badge_info_ident'), table_name='badge_info')
    op.drop_index('ix_badge_info_attendee_id', table_name='badge_info')
    op.drop_table('badge_info')
