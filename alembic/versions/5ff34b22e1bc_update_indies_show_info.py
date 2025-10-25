"""Update Indies show info

Revision ID: 5ff34b22e1bc
Revises: 4112406db1ae
Create Date: 2025-10-24 08:23:00.162539

"""


# revision identifiers, used by Alembic.
revision = '5ff34b22e1bc'
down_revision = '4112406db1ae'
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
    op.add_column('indie_game', sa.Column('link_to_store', sa.Unicode(), server_default='', nullable=False))
    op.drop_column('indie_game', 'twitter')
    op.drop_column('indie_game', 'facebook')
    op.add_column('indie_studio', sa.Column('selling_merch', sa.Integer(), nullable=True))
    op.drop_column('indie_studio', 'selling_at_event')


def downgrade():
    op.add_column('indie_game', sa.Column('facebook', sa.VARCHAR(), server_default=sa.text("''::character varying"), autoincrement=False, nullable=False))
    op.add_column('indie_game', sa.Column('twitter', sa.VARCHAR(), server_default=sa.text("''::character varying"), autoincrement=False, nullable=False))
    op.add_column('indie_studio', sa.Column('selling_at_event', sa.BOOLEAN(), autoincrement=False, nullable=True))
    op.drop_column('indie_studio', 'selling_merch')
    op.drop_column('indie_game', 'link_to_store')
