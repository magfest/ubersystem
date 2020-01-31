"""Add more art show app fields

Revision ID: 6fd0a683af2d
Revises: f812bc84e064
Create Date: 2018-08-24 06:52:17.873616

"""


# revision identifiers, used by Alembic.
revision = '6fd0a683af2d'
down_revision = 'f812bc84e064'
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
    op.add_column('art_show_application', sa.Column('artist_id', sa.Unicode(), server_default='', nullable=False))
    op.add_column('art_show_application', sa.Column('banner_name', sa.Unicode(), server_default='', nullable=False))
    op.add_column('art_show_application', sa.Column('check_payable', sa.Unicode(), server_default='', nullable=False))
    op.add_column('art_show_application', sa.Column('hotel_name', sa.Unicode(), server_default='', nullable=False))
    op.add_column('art_show_application', sa.Column('hotel_room_num', sa.Unicode(), server_default='', nullable=False))


def downgrade():
    op.drop_column('art_show_application', 'hotel_room_num')
    op.drop_column('art_show_application', 'hotel_name')
    op.drop_column('art_show_application', 'check_payable')
    op.drop_column('art_show_application', 'banner_name')
    op.drop_column('art_show_application', 'artist_id')
