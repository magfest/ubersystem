"""Update MIVS game information form for 2025

Revision ID: 3b8019de5b23
Revises: 82ae88b42503
Create Date: 2025-06-15 02:04:09.917804

"""


# revision identifiers, used by Alembic.
revision = '3b8019de5b23'
down_revision = '82ae88b42503'
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
    op.add_column('indie_game', sa.Column('genres_text', sa.Unicode(), server_default='', nullable=False))
    op.add_column('indie_game', sa.Column('requires_gamepad', sa.Boolean(), server_default='False', nullable=False))
    op.add_column('indie_game', sa.Column('is_alumni', sa.Boolean(), server_default='False', nullable=False))
    op.add_column('indie_game', sa.Column('showcase_type', sa.Integer(), server_default='59529741', nullable=False))
    op.drop_column('indie_game', 'shown_events')
    op.drop_column('indie_game', 'alumni_years')
    op.drop_column('indie_game', 'is_multiplayer')
    op.drop_column('indie_game', 'alumni_update')
    op.drop_column('indie_game', 'agreed_reminder2')
    op.drop_column('indie_game', 'agreed_reminder1')


def downgrade():
    op.add_column('indie_game', sa.Column('agreed_reminder1', sa.BOOLEAN(), server_default=sa.text('false'), autoincrement=False, nullable=False))
    op.add_column('indie_game', sa.Column('agreed_reminder2', sa.BOOLEAN(), server_default=sa.text('false'), autoincrement=False, nullable=False))
    op.add_column('indie_game', sa.Column('alumni_update', sa.VARCHAR(), server_default=sa.text("''::character varying"), autoincrement=False, nullable=False))
    op.add_column('indie_game', sa.Column('is_multiplayer', sa.BOOLEAN(), server_default=sa.text('false'), autoincrement=False, nullable=False))
    op.add_column('indie_game', sa.Column('alumni_years', sa.VARCHAR(), server_default=sa.text("''::character varying"), autoincrement=False, nullable=False))
    op.add_column('indie_game', sa.Column('shown_events', sa.VARCHAR(), server_default=sa.text("''::character varying"), autoincrement=False, nullable=False))
    op.drop_column('indie_game', 'is_alumni')
    op.drop_column('indie_game', 'requires_gamepad')
    op.drop_column('indie_game', 'genres_text')
    op.drop_column('indie_game', 'showcase_type')
