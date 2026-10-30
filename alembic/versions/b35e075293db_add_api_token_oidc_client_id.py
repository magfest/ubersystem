"""Add oidc_client_id to api_token

Revision ID: b35e075293db
Revises: 3c9e2a7f41d8
Create Date: 2026-10-19 12:00:00.000000
"""


# revision identifiers, used by Alembic.
revision = 'b35e075293db'
down_revision = '3c9e2a7f41d8'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column('api_token', sa.Column('oidc_client_id', sa.Unicode(), server_default='', nullable=False))


def downgrade():
    op.drop_column('api_token', 'oidc_client_id')
