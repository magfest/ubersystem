"""Update IndieStudio for 2025

Revision ID: 82ae88b42503
Revises: 51daf0d9a514
Create Date: 2025-06-11 15:03:51.104027

"""


# revision identifiers, used by Alembic.
revision = '82ae88b42503'
down_revision = '51daf0d9a514'
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
    op.add_column('indie_developer', sa.Column('gets_emails', sa.Boolean(), server_default='False', nullable=False))
    op.drop_column('indie_developer', 'primary_contact')
    op.add_column('indie_studio', sa.Column('other_links', sa.Unicode(), server_default='', nullable=False))
    op.drop_column('indie_studio', 'address')
    op.drop_column('indie_studio', 'facebook')
    op.drop_column('indie_studio', 'twitter')


def downgrade():
    op.add_column('indie_studio', sa.Column('twitter', sa.VARCHAR(), server_default=sa.text("''::character varying"), autoincrement=False, nullable=False))
    op.add_column('indie_studio', sa.Column('facebook', sa.VARCHAR(), server_default=sa.text("''::character varying"), autoincrement=False, nullable=False))
    op.add_column('indie_studio', sa.Column('address', sa.VARCHAR(), server_default=sa.text("''::character varying"), autoincrement=False, nullable=False))
    op.drop_column('indie_studio', 'other_links')
    op.add_column('indie_developer', sa.Column('primary_contact', sa.BOOLEAN(), server_default=sa.text('false'), autoincrement=False, nullable=False))
    op.drop_column('indie_developer', 'gets_emails')
