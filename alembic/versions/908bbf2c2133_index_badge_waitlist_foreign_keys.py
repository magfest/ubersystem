"""Index badge waitlist foreign keys

Revision ID: 908bbf2c2133
Revises: 0b870f921676
Create Date: 2026-11-18 13:10:00.000000

"""


# revision identifiers, used by Alembic.
revision = '908bbf2c2133'
down_revision = '0b870f921676'
branch_labels = None
depends_on = None

from alembic import op


def upgrade():
    op.create_index(op.f('ix_badge_waitlist_signup_attendee_id'), 'badge_waitlist_signup', ['attendee_id'], unique=False)
    op.create_index(op.f('ix_badge_waitlist_signup_refund_badge_id'), 'badge_waitlist_signup', ['refund_badge_id'], unique=False)
    op.create_index(op.f('ix_badge_waitlist_signup_attendee_account_id'), 'badge_waitlist_signup', ['attendee_account_id'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_badge_waitlist_signup_attendee_account_id'), table_name='badge_waitlist_signup')
    op.drop_index(op.f('ix_badge_waitlist_signup_refund_badge_id'), table_name='badge_waitlist_signup')
    op.drop_index(op.f('ix_badge_waitlist_signup_attendee_id'), table_name='badge_waitlist_signup')
