"""Add checked_in and location columns to apps

Revision ID: 5481f9d61d81
Revises: 6fd0a683af2d
Create Date: 2018-09-25 15:01:15.896928

"""


# revision identifiers, used by Alembic.
revision = '5481f9d61d81'
down_revision = '6fd0a683af2d'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa
import residue


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
    op.add_column('art_show_application', sa.Column('checked_in', residue.UTCDateTime(), nullable=True))
    op.add_column('art_show_application', sa.Column('checked_out', residue.UTCDateTime(), nullable=True))
    op.add_column('art_show_application', sa.Column('locations', sa.Unicode(), server_default='', nullable=False))


def downgrade():
    op.drop_column('art_show_application', 'locations')
    op.drop_column('art_show_application', 'checked_in')
    op.drop_column('art_show_application', 'checked_out')
