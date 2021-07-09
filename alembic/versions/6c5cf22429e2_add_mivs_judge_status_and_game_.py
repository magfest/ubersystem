"""Add MIVS Judge status and game submission tracker

Revision ID: 6c5cf22429e2
Revises: e372e4daf771
Create Date: 2018-09-21 22:25:24.475167

"""


# revision identifiers, used by Alembic.
revision = '6c5cf22429e2'
down_revision = 'e372e4daf771'
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
    op.add_column('indie_judge', sa.Column('no_game_submission', sa.Boolean(), nullable=True))
    op.add_column('indie_judge', sa.Column('status', sa.Integer(), server_default='150891957', nullable=False))


def downgrade():
    op.drop_column('indie_judge', 'status')
    op.drop_column('indie_judge', 'no_game_submission')
