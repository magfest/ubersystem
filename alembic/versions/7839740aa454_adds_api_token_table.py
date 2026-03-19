"""Adds api_token table

Revision ID: 7839740aa454
Revises: 808089d5b2e0
Create Date: 2017-11-11 22:10:28.973153

"""


# revision identifiers, used by Alembic.
revision = '7839740aa454'
down_revision = '808089d5b2e0'
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
    op.create_table('api_token',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('admin_account_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('token', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('access', sa.Unicode(), server_default='', nullable=False),
    sa.Column('name', sa.Unicode(), server_default='', nullable=False),
    sa.Column('description', sa.Unicode(), server_default='', nullable=False),
    sa.Column('issued_time', sa.DateTime(timezone=True), nullable=False),
    sa.Column('revoked_time', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['admin_account_id'], ['admin_account.id'], name=op.f('fk_api_token_admin_account_id_admin_account')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_api_token'))
    )


def downgrade():
    op.drop_table('api_token')
