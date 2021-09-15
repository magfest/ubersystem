"""Add dealer categories

Revision ID: 063eeaf98c57
Revises: b6074f8ea4ab
Create Date: 2017-07-21 03:24:02.771982

"""


# revision identifiers, used by Alembic.
revision = '063eeaf98c57'
down_revision = 'b6074f8ea4ab'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa



try:
    is_sqlite = op.get_context().dialect.name == 'sqlite'
except:
    is_sqlite = False

if is_sqlite:
    op.get_context().connection.execute('PRAGMA foreign_keys=ON;')
    utcnow_server_default = "(datetime('now', 'utc'))"
else:
    utcnow_server_default = "timezone('utc', current_timestamp)"


def upgrade():
    op.add_column('group', sa.Column('categories', sa.Unicode(), server_default='', nullable=False))
    op.add_column('group', sa.Column('categories_text', sa.Unicode(), server_default='', nullable=False))


def downgrade():
    op.drop_column('group', 'categories_text')
    op.drop_column('group', 'categories')
