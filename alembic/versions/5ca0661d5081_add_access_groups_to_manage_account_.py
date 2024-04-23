"""Add Access Groups to manage account permissions.

Revision ID: 5ca0661d5081
Revises: bba880ef5bbd
Create Date: 2019-08-20 04:04:37.112614

"""


# revision identifiers, used by Alembic.
revision = '5ca0661d5081'
down_revision = 'bba880ef5bbd'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.types import UUID


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

# ===========================================================================
# HOWTO: Handle alter statements in SQLite
#
# def upgrade():
#     if is_sqlite:
#         with op.batch_alter_table('table_name', reflect_kwargs=sqlite_reflect_kwargs) as batch_op:
#             batch_op.alter_column('column_name', type_=sa.Unicode(), server_default='', nullable=False)
#     else:
#         op.alter_column('table_name', 'column_name', type_=sa.Unicode(), server_default='', nullable=False)
#
# ===========================================================================


def upgrade():
    op.create_table('access_group',
    sa.Column('id', UUID(), nullable=False),
    sa.Column('name', sa.Unicode(), server_default='', nullable=False),
    sa.Column('access', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('read_only_access', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_access_group'))
    )
    op.add_column('admin_account', sa.Column('access_group_id', UUID(), nullable=True))
    op.create_foreign_key(op.f('fk_admin_account_access_group_id_access_group'), 'admin_account', 'access_group', ['access_group_id'], ['id'], ondelete='SET NULL')


def downgrade():
    op.drop_constraint(op.f('fk_admin_account_access_group_id_access_group'), 'admin_account', type_='foreignkey')
    op.drop_column('admin_account', 'access_group_id')
    op.drop_table('access_group')
