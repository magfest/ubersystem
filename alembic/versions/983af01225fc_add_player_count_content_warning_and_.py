"""Add player count, content warning, and photosensitivity warning to MIVS games

Revision ID: 983af01225fc
Revises: f1a8794a398f
Create Date: 2024-08-01 02:28:06.735773

"""


# revision identifiers, used by Alembic.
revision = '983af01225fc'
down_revision = 'f1a8794a398f'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
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
    op.add_column('indie_game', sa.Column('is_multiplayer', sa.Boolean(), server_default='False', nullable=False))
    op.add_column('indie_game', sa.Column('content_warning', sa.Boolean(), server_default='False', nullable=False))
    op.add_column('indie_game', sa.Column('photosensitive_warning', sa.Boolean(), server_default='False', nullable=False))
    op.add_column('indie_game', sa.Column('warning_desc', sa.Unicode(), server_default='', nullable=False))


def downgrade():
    op.drop_column('indie_game', 'warning_desc')
    op.drop_column('indie_game', 'content_warning')
    op.drop_column('indie_game', 'photosensitive_warning')
    op.drop_column('indie_game', 'is_multiplayer')
