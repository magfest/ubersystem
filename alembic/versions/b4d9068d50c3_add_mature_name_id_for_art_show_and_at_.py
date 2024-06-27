"""Add mature name/id for art show and at-con contact fields

Revision ID: b4d9068d50c3
Revises: 5f6cb43ef3ca
Create Date: 2024-06-19 16:01:43.020314

"""


# revision identifiers, used by Alembic.
revision = 'b4d9068d50c3'
down_revision = '5f6cb43ef3ca'
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
    op.add_column('art_show_application', sa.Column('banner_name_ad', sa.Unicode(), server_default='', nullable=False))
    op.add_column('art_show_application', sa.Column('artist_id_ad', sa.Unicode(), server_default='', nullable=False))
    op.add_column('art_show_application', sa.Column('contact_at_con', sa.Unicode(), server_default='', nullable=False))


def downgrade():
    op.drop_column('art_show_application', 'contact_at_con')
    op.drop_column('art_show_application', 'artist_id_ad')
    op.drop_column('art_show_application', 'banner_name_ad')
