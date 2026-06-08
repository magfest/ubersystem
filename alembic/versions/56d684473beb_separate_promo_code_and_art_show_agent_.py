"""Separate promo code and art show agent codes.

Revision ID: 56d684473beb
Revises: 7c43e4352bb0
Create Date: 2024-05-31 03:19:53.022061

"""


# revision identifiers, used by Alembic.
revision = '56d684473beb'
down_revision = '7c43e4352bb0'
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
    op.create_table('art_show_agent_code',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('app_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('attendee_id', sa.Uuid(as_uuid=False), nullable=True),
    sa.Column('code', sa.Unicode(), server_default='', nullable=False),
    sa.Column('cancelled', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['app_id'], ['art_show_application.id'], name=op.f('fk_art_show_agent_code_app_id_art_show_application')),
    sa.ForeignKeyConstraint(['attendee_id'], ['attendee.id'], name=op.f('fk_art_show_agent_code_attendee_id_attendee'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_art_show_agent_code')),
    sa.UniqueConstraint('attendee_id', name=op.f('uq_art_show_agent_code_attendee_id'))
    )
    op.drop_constraint('fk_art_show_application_agent_id_attendee', 'art_show_application', type_='foreignkey')
    op.drop_column('art_show_application', 'agent_code')
    op.drop_column('art_show_application', 'agent_id')


def downgrade():
    op.add_column('art_show_application', sa.Column('agent_id', postgresql.UUID(), autoincrement=False, nullable=True))
    op.add_column('art_show_application', sa.Column('agent_code', sa.VARCHAR(), server_default=sa.text("''::character varying"), autoincrement=False, nullable=False))
    op.create_foreign_key('fk_art_show_application_agent_id_attendee', 'art_show_application', 'attendee', ['agent_id'], ['id'], ondelete='SET NULL')
    op.drop_table('art_show_agent_code')
