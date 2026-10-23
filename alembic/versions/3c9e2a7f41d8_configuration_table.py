"""Add the configuration table for settings stored in the database

Revision ID: 3c9e2a7f41d8
Revises: daeb5dee6fc4
Create Date: 2026-10-15 12:00:00.000000
"""


# revision identifiers, used by Alembic.
revision = '3c9e2a7f41d8'
down_revision = 'daeb5dee6fc4'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


def upgrade():
    op.create_table('configuration',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('created', sa.DateTime(timezone=True), server_default=sa.text("timezone('utc', current_timestamp)"), nullable=False),
    sa.Column('last_updated', sa.DateTime(timezone=True), server_default=sa.text("timezone('utc', current_timestamp)"), nullable=False),
    sa.Column('external_id', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('last_synced', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('section_name', sa.String(length=255), server_default='', nullable=False),
    sa.Column('config_data', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_configuration')),
    sa.UniqueConstraint('section_name', name=op.f('uq_configuration_section_name'))
    )


def downgrade():
    op.drop_table('configuration')
