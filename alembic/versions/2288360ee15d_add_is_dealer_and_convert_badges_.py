"""Add is_dealer and convert_badges columns to groups

Revision ID: 2288360ee15d
Revises: f30b7120de0b
Create Date: 2024-04-05 18:00:04.845183

"""


# revision identifiers, used by Alembic.
revision = '2288360ee15d'
down_revision = 'f30b7120de0b'
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
    op.add_column('group', sa.Column('convert_badges', sa.Boolean(), server_default='False', nullable=False))
    op.add_column('group', sa.Column('is_dealer', sa.Boolean(), server_default='False', nullable=False))


def downgrade():
    op.drop_column('group', 'is_dealer')
    op.drop_column('group', 'convert_badges')
