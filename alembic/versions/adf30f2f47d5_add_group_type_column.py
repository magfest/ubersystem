"""Add group type column

Revision ID: adf30f2f47d5
Revises: 5c14f5a350dd
Create Date: 2017-09-11 16:27:19.276277

"""


# revision identifiers, used by Alembic.
revision = 'adf30f2f47d5'
down_revision = '5c14f5a350dd'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


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
        with op.batch_alter_table('band', reflect_kwargs=sqlite_reflect_kwargs) as batch_op:
            batch_op.add_column(sa.Column('group_type', sa.Integer(), server_default='147019101', nullable=False))
    else:
        op.add_column('band', sa.Column('group_type', sa.Integer(), server_default='147019101', nullable=False))


def downgrade():
    op.drop_column('band', 'group_type')
