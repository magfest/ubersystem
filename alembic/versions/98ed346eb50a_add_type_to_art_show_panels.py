"""Add type to art show panels

Revision ID: 98ed346eb50a
Revises: 538247a4b201
Create Date: 2025-12-01 02:55:41.577931

"""


# revision identifiers, used by Alembic.
revision = '98ed346eb50a'
down_revision = '538247a4b201'
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
    op.add_column('art_show_panel', sa.Column('panel_type', sa.Integer(), server_default='117119638', nullable=False))
    op.drop_constraint(op.f('uq_art_show_panel_gallery'), 'art_show_panel', type_='unique')
    op.create_unique_constraint(op.f('uq_art_show_panel_gallery'), 'art_show_panel', ['gallery', 'panel_type', 'origin_x', 'origin_y', 'terminus_x', 'terminus_y'])


def downgrade():
    op.drop_constraint(op.f('uq_art_show_panel_gallery'), 'art_show_panel', type_='unique')
    op.create_unique_constraint(op.f('uq_art_show_panel_gallery'), 'art_show_panel', ['gallery', 'origin_x', 'origin_y', 'terminus_x', 'terminus_y'])
    op.drop_column('art_show_panel', 'panel_type')
