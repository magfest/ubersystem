"""Adds is_setup/teardown_approval_exempt columns to department

Revision ID: 808089d5b2e0
Revises: d3da548acd2e
Create Date: 2017-11-11 15:49:20.141843

"""


# revision identifiers, used by Alembic.
revision = '808089d5b2e0'
down_revision = 'd3da548acd2e'
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
    if is_sqlite:
        connection = op.get_bind()
        connection.execute('PRAGMA foreign_keys = OFF;')
        with op.batch_alter_table('department', reflect_kwargs=sqlite_reflect_kwargs) as batch_op:
            batch_op.add_column(sa.Column('is_setup_approval_exempt', sa.Boolean(), server_default='False', default=False, nullable=False))
            batch_op.add_column(sa.Column('is_teardown_approval_exempt', sa.Boolean(), server_default='False', default=False, nullable=False))
    else:
        op.add_column('department', sa.Column('is_setup_approval_exempt', sa.Boolean(), server_default='False', default=False, nullable=False))
        op.add_column('department', sa.Column('is_teardown_approval_exempt', sa.Boolean(), server_default='False', default=False, nullable=False))



def downgrade():
    if is_sqlite:
        with op.batch_alter_table('department', reflect_kwargs=sqlite_reflect_kwargs) as batch_op:
            batch_op.drop_column('is_teardown_approval_exempt')
            batch_op.drop_column('is_setup_approval_exempt')
    else:
        op.drop_column('department', 'is_teardown_approval_exempt')
        op.drop_column('department', 'is_setup_approval_exempt')
