"""Add composite index on attendee email, first_name, and last_name

Revision ID: b4e7a1c92d3f
Revises: 3c9e2a7f41d8
Create Date: 2026-10-29 15:30:00.000000
"""


# revision identifiers, used by Alembic.
revision = 'b4e7a1c92d3f'
down_revision = '3c9e2a7f41d8'
branch_labels = None
depends_on = None

from alembic import op


def upgrade():
    op.create_index('ix_attendee_email_first_name_last_name', 'attendee', ['email', 'first_name', 'last_name'],
                    unique=False, if_not_exists=True)


def downgrade():
    op.drop_index('ix_attendee_email_first_name_last_name', table_name='attendee', if_exists=True)
