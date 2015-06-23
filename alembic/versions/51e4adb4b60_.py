"""Add WatchList table

Revision ID: 51e4adb4b60
Revises: 
Create Date: 2015-06-19 12:06:10.753671

"""

# revision identifiers, used by Alembic.
revision = '51e4adb4b60'
down_revision = None
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa
from sideboard.lib.sa import UUID


def upgrade():
    op.create_table(
        'watch_list',
        sa.Column('id', UUID, primary_key=True, default=lambda: str(uuid4())),
        sa.Column('first_name', sa.UnicodeText(), nullable=False),
        sa.Column('last_name', sa.UnicodeText(), nullable=False),
        sa.Column('disabled', sa.Boolean(), default=False),
        sa.Column('reason', sa.UnicodeText(), nullable=False),
        sa.Column('action', sa.UnicodeText(), nullable=False),
    )


def downgrade():
    op.drop_table('watch_list')
