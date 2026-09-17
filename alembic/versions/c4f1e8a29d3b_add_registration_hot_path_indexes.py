"""Add indexes for the registration hot path

Revision ID: c4f1e8a29d3b
Revises: b7c3d9e41f02
Create Date: 2026-09-16 18:30:00.000000
"""


# revision identifiers, used by Alembic.
revision = 'c4f1e8a29d3b'
down_revision = 'b7c3d9e41f02'
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

# Must match AttendeeAccount.normalized_email's SQL expression exactly, or the
# planner will not use the index.
NORMALIZED_EMAIL = sa.text("replace(lower(trim(email)), '.', '')")


def upgrade():
    op.create_index('ix_attendee_account_normalized_email', 'attendee_account',
                    ['email'] if is_sqlite else [NORMALIZED_EMAIL], unique=False, if_not_exists=True)
    op.create_index('ix_attendee_account_sso_id', 'attendee_account', ['sso_id'], unique=False, if_not_exists=True)
    op.create_index('ix_admin_account_sso_id', 'admin_account', ['sso_id'], unique=False, if_not_exists=True)
    op.create_index('ix_badge_info_free_ident', 'badge_info', ['ident'], unique=False, if_not_exists=True,
                    postgresql_where=sa.text('attendee_id IS NULL'), sqlite_where=sa.text('attendee_id IS NULL'))
    op.create_index('ix_receipt_item_receipt_id', 'receipt_item', ['receipt_id'], unique=False, if_not_exists=True)
    op.create_index('ix_receipt_transaction_receipt_id', 'receipt_transaction', ['receipt_id'], unique=False, if_not_exists=True)
    op.create_index('ix_receipt_discount_receipt_id', 'receipt_discount', ['receipt_id'], unique=False, if_not_exists=True)


def downgrade():
    op.drop_index('ix_receipt_discount_receipt_id', table_name='receipt_discount', if_exists=True)
    op.drop_index('ix_receipt_transaction_receipt_id', table_name='receipt_transaction', if_exists=True)
    op.drop_index('ix_receipt_item_receipt_id', table_name='receipt_item', if_exists=True)
    op.drop_index('ix_badge_info_free_ident', table_name='badge_info', if_exists=True)
    op.drop_index('ix_admin_account_sso_id', table_name='admin_account', if_exists=True)
    op.drop_index('ix_attendee_account_sso_id', table_name='attendee_account', if_exists=True)
    op.drop_index('ix_attendee_account_normalized_email', table_name='attendee_account', if_exists=True)
