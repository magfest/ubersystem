"""Add new MIVS game scoring columns

Revision ID: bf427bc2a7f2
Revises: 72f97bdad2fa
Create Date: 2018-10-05 17:04:48.477995

"""


# revision identifiers, used by Alembic.
revision = 'bf427bc2a7f2'
down_revision = '72f97bdad2fa'
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
    op.add_column('indie_game_review', sa.Column('design_score', sa.Integer(), server_default='0', nullable=False))
    op.add_column('indie_game_review', sa.Column('enjoyment_score', sa.Integer(), server_default='0', nullable=False))
    op.add_column('indie_game_review', sa.Column('readiness_score', sa.Integer(), server_default='0', nullable=False))
    op.drop_column('indie_game_review', 'game_score')


def downgrade():
    op.add_column('indie_game_review', sa.Column('game_score', sa.INTEGER(), server_default=sa.text('0'), autoincrement=False, nullable=False))
    op.drop_column('indie_game_review', 'readiness_score')
    op.drop_column('indie_game_review', 'enjoyment_score')
    op.drop_column('indie_game_review', 'design_score')
