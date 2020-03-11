"""Add Code of Conduct and Data Policy agreement columns

Revision ID: 8888a0f4c1ef
Revises: 07f752ec9b7c
Create Date: 2019-09-01 01:17:02.604266

"""


# revision identifiers, used by Alembic.
revision = '8888a0f4c1ef'
down_revision = '07f752ec9b7c'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa



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
    op.add_column('indie_developer', sa.Column('agreed_coc', sa.Boolean(), server_default='False', nullable=False))
    op.add_column('indie_developer', sa.Column('agreed_data_policy', sa.Boolean(), server_default='False', nullable=False))


def downgrade():
    op.drop_column('indie_developer', 'agreed_data_policy')
    op.drop_column('indie_developer', 'agreed_coc')
