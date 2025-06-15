"""Add panel configuration to departments

Revision ID: 4884c82c2101
Revises: fbb26404edc5
Create Date: 2025-05-27 11:06:17.829828

"""


# revision identifiers, used by Alembic.
revision = '4884c82c2101'
down_revision = 'fbb26404edc5'
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
    op.add_column('department', sa.Column('from_email', sa.Unicode(), server_default='', nullable=False))
    op.add_column('department', sa.Column('manages_panels', sa.Boolean(), server_default='False', nullable=False))
    op.add_column('department', sa.Column('panels_desc', sa.Unicode(), server_default='', nullable=False))
    op.alter_column('panel_application', 'department',
               existing_type=sa.INTEGER(),
               type_=sa.Unicode(),
               existing_nullable=False,
               existing_server_default=sa.text('39626696'))


def downgrade():
    op.drop_column('department', 'panels_desc')
    op.drop_column('department', 'manages_panels')
    op.drop_column('department', 'from_email')
    op.drop_column('panel_application', 'department')
    op.add_column('panel_application', sa.Column('department', sa.Integer(), server_default='39626696', nullable=False))
