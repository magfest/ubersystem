"""Add API Job table

Revision ID: c7a439f29c1c
Revises: 81b45e3d967c
Create Date: 2022-06-09 02:26:35.790794

"""


# revision identifiers, used by Alembic.
revision = 'c7a439f29c1c'
down_revision = '81b45e3d967c'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


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
    op.create_table('api_job',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('admin_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('admin_name', sa.Unicode(), server_default='', nullable=False),
    sa.Column('queued', sa.DateTime(timezone=True), nullable=True),
    sa.Column('completed', sa.DateTime(timezone=True), nullable=True),
    sa.Column('cancelled', sa.DateTime(timezone=True), nullable=True),
    sa.Column('job_name', sa.Unicode(), server_default='', nullable=False),
    sa.Column('target_server', sa.Unicode(), server_default='', nullable=False),
    sa.Column('query', sa.Unicode(), server_default='', nullable=False),
    sa.Column('api_token', sa.Unicode(), server_default='', nullable=False),
    sa.Column('errors', sa.Unicode(), server_default='', nullable=False),
    sa.Column('json_data', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.ForeignKeyConstraint(['admin_id'], ['admin_account.id'], name=op.f('fk_api_job_admin_id_admin_account')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_api_job'))
    )


def downgrade():
    op.drop_table('api_job')
