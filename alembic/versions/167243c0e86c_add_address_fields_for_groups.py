"""Add address fields for groups

Revision ID: 167243c0e86c
Revises: 71991162a59c
Create Date: 2017-07-12 22:34:43.889923

"""


# revision identifiers, used by Alembic.
revision = '167243c0e86c'
down_revision = '71991162a59c'
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
    op.alter_column('group', 'address', new_column_name='address1')
    op.add_column('group', sa.Column('address2', sa.Unicode(), server_default='', nullable=False))
    op.add_column('group', sa.Column('city', sa.Unicode(), server_default='', nullable=False))
    op.add_column('group', sa.Column('country', sa.Unicode(), server_default='', nullable=False))
    op.add_column('group', sa.Column('region', sa.Unicode(), server_default='', nullable=False))
    op.add_column('group', sa.Column('zip_code', sa.Unicode(), server_default='', nullable=False))


def downgrade():
    op.drop_column('group', 'zip_code')
    op.drop_column('group', 'region')
    op.drop_column('group', 'country')
    op.drop_column('group', 'city')
    op.drop_column('group', 'address2')
    op.alter_column('group', 'address1', new_column_name='address')
