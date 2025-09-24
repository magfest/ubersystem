"""Add fields for indie retro submissions

Revision ID: 2c5035b1ae4e
Revises: ce0d3ef16e46
Create Date: 2025-08-21 10:06:31.871103

"""


# revision identifiers, used by Alembic.
revision = '2c5035b1ae4e'
down_revision = 'ce0d3ef16e46'
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
    op.add_column('indie_game', sa.Column('publisher_name', sa.Unicode(), server_default='', nullable=False))
    op.add_column('indie_game', sa.Column('release_date', sa.Unicode(), server_default='', nullable=False))
    op.add_column('indie_game', sa.Column('other_assets', sa.Unicode(), server_default='', nullable=False))
    op.add_column('indie_game', sa.Column('in_person', sa.Boolean(), server_default='False', nullable=False))
    op.add_column('indie_game', sa.Column('delivery_method', sa.Integer(), nullable=True))


def downgrade():
    op.drop_column('indie_game', 'delivery_method')
    op.drop_column('indie_game', 'in_person')
    op.drop_column('indie_game', 'other_assets')
    op.drop_column('indie_game', 'release_date')
    op.drop_column('indie_game', 'publisher_name')
