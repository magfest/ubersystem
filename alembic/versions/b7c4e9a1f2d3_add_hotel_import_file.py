"""Add hotel_import_file.

Retains raw hotel confirmation/cancellation upload files (from the hotel portal
or the admin upload) so they can be reviewed and re-applied after the fact.

Separate from a7d3f0c1e2b4 because that revision was already applied in
deployed environments; editing it would not create the table there.

Revision ID: b7c4e9a1f2d3
Revises: a7d3f0c1e2b4
Create Date: 2026-06-23 00:00:00.000000
"""

revision = 'b7c4e9a1f2d3'
down_revision = 'a7d3f0c1e2b4'
branch_labels = None
depends_on = None

from alembic import op
from sqlalchemy.dialects import postgresql
import sqlalchemy as sa


def upgrade():
    op.create_table('hotel_import_file',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('created', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_updated', sa.DateTime(timezone=True), nullable=False),
    sa.Column('external_id', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('last_synced', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('hotel_id', sa.Uuid(as_uuid=False), nullable=True),
    sa.Column('filename', sa.Unicode(), nullable=False),
    sa.Column('content_type', sa.Unicode(), nullable=False),
    sa.Column('filepath', sa.Unicode(), nullable=False),
    sa.Column('size', sa.Integer(), nullable=False),
    sa.Column('source', sa.Unicode(), nullable=False),
    sa.Column('uploaded_by', sa.Unicode(), nullable=False),
    sa.Column('uploaded_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_count', sa.Integer(), nullable=False),
    sa.Column('unchanged_count', sa.Integer(), nullable=False),
    sa.Column('note', sa.Unicode(), nullable=False),
    sa.ForeignKeyConstraint(['hotel_id'], ['lottery_hotel.id'], name=op.f('fk_hotel_import_file_hotel_id_lottery_hotel')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_hotel_import_file'))
    )


def downgrade():
    op.drop_table('hotel_import_file')
