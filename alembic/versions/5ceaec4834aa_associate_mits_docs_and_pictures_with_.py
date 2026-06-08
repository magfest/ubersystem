"""Associate MITS docs and pictures with games instead of teams

Revision ID: 5ceaec4834aa
Revises: 4036e1fdb9ee
Create Date: 2020-04-14 23:23:35.417496

"""


# revision identifiers, used by Alembic.
revision = '5ceaec4834aa'
down_revision = '4036e1fdb9ee'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


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
    op.add_column('mits_document', sa.Column('game_id', sa.Uuid(as_uuid=False), nullable=False))
    op.drop_constraint('fk_mits_document_team_id_mits_team', 'mits_document', type_='foreignkey')
    op.create_foreign_key(op.f('fk_mits_document_game_id_mits_game'), 'mits_document', 'mits_game', ['game_id'], ['id'])
    op.drop_column('mits_document', 'team_id')
    op.add_column('mits_picture', sa.Column('game_id', sa.Uuid(as_uuid=False), nullable=False))
    op.drop_constraint('fk_mits_picture_team_id_mits_team', 'mits_picture', type_='foreignkey')
    op.create_foreign_key(op.f('fk_mits_picture_game_id_mits_game'), 'mits_picture', 'mits_game', ['game_id'], ['id'])
    op.drop_column('mits_picture', 'team_id')


def downgrade():
    op.add_column('mits_picture', sa.Column('team_id', postgresql.UUID(), autoincrement=False, nullable=False))
    op.drop_constraint(op.f('fk_mits_picture_game_id_mits_game'), 'mits_picture', type_='foreignkey')
    op.create_foreign_key('fk_mits_picture_team_id_mits_team', 'mits_picture', 'mits_team', ['team_id'], ['id'])
    op.drop_column('mits_picture', 'game_id')
    op.add_column('mits_document', sa.Column('team_id', postgresql.UUID(), autoincrement=False, nullable=False))
    op.drop_constraint(op.f('fk_mits_document_game_id_mits_game'), 'mits_document', type_='foreignkey')
    op.create_foreign_key('fk_mits_document_team_id_mits_team', 'mits_document', 'mits_team', ['team_id'], ['id'])
    op.drop_column('mits_document', 'game_id')
