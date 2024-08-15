"""Add schedule description and separate recording preference option for panels

Revision ID: 0ba9060b0434
Revises: 983af01225fc
Create Date: 2024-08-08 03:37:03.691021

"""


# revision identifiers, used by Alembic.
revision = '0ba9060b0434'
down_revision = '983af01225fc'
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
    op.add_column('event', sa.Column('public_description', sa.Unicode(), server_default='', nullable=False))
    op.add_column('panel_application', sa.Column('public_description', sa.Unicode(), server_default='', nullable=False))
    op.add_column('panel_application', sa.Column('record', sa.Integer(), server_default='227291107', nullable=False))


def downgrade():
    op.drop_column('panel_application', 'record')
    op.drop_column('panel_application', 'public_description')
    op.drop_column('event', 'public_description')
