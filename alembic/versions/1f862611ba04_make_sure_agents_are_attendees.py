"""Make sure agents are attendees

Revision ID: 1f862611ba04
Revises: a18bda430e7f
Create Date: 2018-05-19 14:37:54.148958

"""


# revision identifiers, used by Alembic.
revision = '1f862611ba04'
down_revision = 'a18bda430e7f'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa
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
    op.add_column('art_show_application', sa.Column('agent_code', sa.Unicode(), server_default='', nullable=False))
    op.add_column('art_show_application', sa.Column('agent_id', residue.UUID(), nullable=True))
    op.create_foreign_key(op.f('fk_art_show_application_agent_id_attendee'), 'art_show_application', 'attendee', ['agent_id'], ['id'], ondelete='SET NULL')
    op.drop_column('art_show_application', 'agent_name')


def downgrade():
    op.add_column('art_show_application', sa.Column('agent_name', sa.VARCHAR(), server_default=sa.text("''::character varying"), autoincrement=False, nullable=False))
    op.drop_constraint(op.f('fk_art_show_application_agent_id_attendee'), 'art_show_application', type_='foreignkey')
    op.drop_column('art_show_application', 'agent_id')
    op.drop_column('art_show_application', 'agent_code')
