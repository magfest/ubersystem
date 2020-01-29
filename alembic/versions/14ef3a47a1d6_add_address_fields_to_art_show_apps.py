"""Add address fields to art show apps.

Revision ID: 14ef3a47a1d6
Revises: 5481f9d61d81
Create Date: 2018-09-28 16:16:54.438418

"""


# revision identifiers, used by Alembic.
revision = '14ef3a47a1d6'
down_revision = '5481f9d61d81'
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
    op.add_column('art_show_application', sa.Column('address1', sa.Unicode(), server_default='', nullable=False))
    op.add_column('art_show_application', sa.Column('address2', sa.Unicode(), server_default='', nullable=False))
    op.add_column('art_show_application', sa.Column('business_name', sa.Unicode(), server_default='', nullable=False))
    op.add_column('art_show_application', sa.Column('city', sa.Unicode(), server_default='', nullable=False))
    op.add_column('art_show_application', sa.Column('country', sa.Unicode(), server_default='', nullable=False))
    op.add_column('art_show_application', sa.Column('region', sa.Unicode(), server_default='', nullable=False))
    op.add_column('art_show_application', sa.Column('zip_code', sa.Unicode(), server_default='', nullable=False))


def downgrade():
    op.drop_column('art_show_application', 'zip_code')
    op.drop_column('art_show_application', 'region')
    op.drop_column('art_show_application', 'country')
    op.drop_column('art_show_application', 'city')
    op.drop_column('art_show_application', 'business_name')
    op.drop_column('art_show_application', 'address2')
    op.drop_column('art_show_application', 'address1')
