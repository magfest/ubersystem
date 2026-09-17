"""Add more indexes for the registration hot path

Revision ID: e5b2a7c91d40
Revises: c4f1e8a29d3b
Create Date: 2026-09-16 23:40:00.000000
"""


# revision identifiers, used by Alembic.
revision = 'e5b2a7c91d40'
down_revision = 'c4f1e8a29d3b'
branch_labels = None
depends_on = None

from alembic import op


def upgrade():
    op.create_index('ix_attendee_badge_pickup_group_id', 'attendee', ['badge_pickup_group_id'], unique=False, if_not_exists=True)
    op.create_index('ix_attendee_email', 'attendee', ['email'], unique=False, if_not_exists=True)
    op.create_index('ix_receipt_transaction_intent_id', 'receipt_transaction', ['intent_id'], unique=False, if_not_exists=True)
    op.create_index('ix_receipt_item_txn_id', 'receipt_item', ['txn_id'], unique=False, if_not_exists=True)
    op.create_index('ix_email_fk_id', 'email', ['fk_id'], unique=False, if_not_exists=True)


def downgrade():
    op.drop_index('ix_email_fk_id', table_name='email', if_exists=True)
    op.drop_index('ix_receipt_item_txn_id', table_name='receipt_item', if_exists=True)
    op.drop_index('ix_receipt_transaction_intent_id', table_name='receipt_transaction', if_exists=True)
    op.drop_index('ix_attendee_email', table_name='attendee', if_exists=True)
    op.drop_index('ix_attendee_badge_pickup_group_id', table_name='attendee', if_exists=True)
