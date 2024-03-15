"""Add default_cost column to attendee and art show apps

Revision ID: 62f0d1d32a49
Revises: 1dc129c4c4f0
Create Date: 2023-11-05 03:49:37.649953

"""


# revision identifiers, used by Alembic.
revision = '62f0d1d32a49'
down_revision = '1dc129c4c4f0'
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
#             batch_op.alter_column('column_name', type_=sa.Unicode(), server_default='', nullable=True)
#     else:
#         op.alter_column('table_name', 'column_name', type_=sa.Unicode(), server_default='', nullable=True)
#
# ===========================================================================


def upgrade():
    op.add_column('art_show_application', sa.Column('default_cost', sa.Integer(), nullable=True))
    op.add_column('attendee', sa.Column('default_cost', sa.Integer(), nullable=True))


def downgrade():
    op.drop_column('attendee', 'default_cost')
    op.drop_column('art_show_application', 'default_cost')
