"""Add badge waitlist

Revision ID: 217f28ecbe95
Revises: 8b1f4d6e2a90
Create Date: 2026-10-20 15:39:17.006510

"""


# revision identifiers, used by Alembic.
revision = '217f28ecbe95'
down_revision = '8b1f4d6e2a90'
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
    op.create_table('badge_waitlist_signup',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('created', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_updated', sa.DateTime(timezone=True), nullable=False),
    sa.Column('external_id', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('last_synced', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('attendee_id', sa.Uuid(as_uuid=False), nullable=True),
    sa.Column('attendee_account_id', sa.Uuid(as_uuid=False), nullable=True),
    sa.Column('refund_badge_id', sa.Uuid(as_uuid=False), nullable=True),
    sa.Column('signup_time', sa.DateTime(timezone=True), nullable=False),
    sa.Column('offered_badge', sa.DateTime(timezone=True), nullable=True),
    sa.Column('status', sa.Integer(), server_default='196944751', nullable=False),
    sa.Column('waitlist_type', sa.Integer(), nullable=False),
    sa.Column('waitlist_position', sa.Integer(), nullable=False),
    sa.Column('signup_order', sa.Integer(), nullable=False),
    sa.Column('first_name', sa.Unicode(), nullable=False),
    sa.Column('last_name', sa.Unicode(), nullable=False),
    sa.Column('legal_name', sa.Unicode(), nullable=False),
    sa.Column('email', sa.Unicode(), nullable=False),
    sa.Column('birthdate', sa.Date(), nullable=True),
    sa.Column('offer_without_adult', sa.Boolean(), nullable=False),
    sa.ForeignKeyConstraint(['attendee_account_id'], ['attendee_account.id'], name=op.f('fk_badge_waitlist_signup_attendee_account_id_attendee_account')),
    sa.ForeignKeyConstraint(['attendee_id'], ['attendee.id'], name=op.f('fk_badge_waitlist_signup_attendee_id_attendee')),
    sa.ForeignKeyConstraint(['refund_badge_id'], ['attendee.id'], name=op.f('fk_badge_waitlist_signup_refund_badge_id_attendee')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_badge_waitlist_signup'))
    )
    op.create_index(op.f('ix_badge_waitlist_signup_status'), 'badge_waitlist_signup', ['status'], unique=False)
    op.create_index(op.f('ix_badge_waitlist_signup_offered_badge'), 'badge_waitlist_signup', ['offered_badge'], unique=False)
    op.create_index(op.f('ix_badge_waitlist_signup_waitlist_position'), 'badge_waitlist_signup', ['waitlist_position'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_badge_waitlist_signup_waitlist_position'), table_name='badge_waitlist_signup')
    op.drop_index(op.f('ix_badge_waitlist_signup_offered_badge'), table_name='badge_waitlist_signup')
    op.drop_index(op.f('ix_badge_waitlist_signup_status'), table_name='badge_waitlist_signup')
    op.drop_table('badge_waitlist_signup')
