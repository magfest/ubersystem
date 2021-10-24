"""Adds more band info columns

Revision ID: 6aef7396c197
Revises: a3d71270256c
Create Date: 2017-08-05 18:22:17.589936

"""


# revision identifiers, used by Alembic.
revision = '6aef7396c197'
down_revision = 'a3d71270256c'
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
    op.add_column('band_panel', sa.Column('other_tech_needs', sa.Unicode(), server_default='', nullable=False))
    op.add_column('band_bio', sa.Column('teaser_song_url', sa.Unicode(), server_default='', nullable=False))


def downgrade():
    op.drop_column('band_panel', 'other_tech_needs')
    op.drop_column('band_bio', 'teaser_song_url')
