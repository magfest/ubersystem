"""Stage DB pre-migration

Revision ID: 16acd13b4aa1
Revises: 
Create Date: 2015-06-24 17:30:19.858709

"""

# revision identifiers, used by Alembic.
revision = '16acd13b4aa1'
down_revision = ''
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.alter_column('job', 'weight', server_default=1)    
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
    
