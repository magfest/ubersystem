"""Remove MIVS video review columns

Revision ID: fa869546b8ca
Revises: 2cd71c52889e
Create Date: 2019-08-23 07:31:38.374122

"""


# revision identifiers, used by Alembic.
revision = 'fa869546b8ca'
down_revision = '2cd71c52889e'
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
    op.drop_column('indie_game', 'video_submitted')
    op.drop_column('indie_game_review', 'video_review')
    op.drop_column('indie_game_review', 'video_score')


def downgrade():
    op.add_column('indie_game_review', sa.Column('video_score', sa.INTEGER(), server_default=sa.text('196944751'), autoincrement=False, nullable=False))
    op.add_column('indie_game_review', sa.Column('video_review', sa.VARCHAR(), server_default=sa.text("''::character varying"), autoincrement=False, nullable=False))
    op.add_column('indie_game', sa.Column('video_submitted', sa.BOOLEAN(), server_default=sa.text('false'), autoincrement=False, nullable=False))
