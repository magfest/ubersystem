"""Add panel applicants and indie teams to attendee accounts

Revision ID: 116b5a9b66c1
Revises: f7f8a2662545
Create Date: 2026-04-15 11:15:27.487637

"""


# revision identifiers, used by Alembic.
revision = '116b5a9b66c1'
down_revision = 'f7f8a2662545'
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
    op.add_column('indie_studio', sa.Column('attendee_account_id', sa.Uuid(as_uuid=False), nullable=True))
    op.create_foreign_key(op.f('fk_indie_studio_attendee_account_id_attendee_account'), 'indie_studio', 'attendee_account', ['attendee_account_id'], ['id'])
    op.add_column('mits_team', sa.Column('attendee_account_id', sa.Uuid(as_uuid=False), nullable=True))
    op.create_foreign_key(op.f('fk_mits_team_attendee_account_id_attendee_account'), 'mits_team', 'attendee_account', ['attendee_account_id'], ['id'])
    op.add_column('panel_application', sa.Column('attendee_account_id', sa.Uuid(as_uuid=False), nullable=True))
    op.create_foreign_key(op.f('fk_panel_application_attendee_account_id_attendee_account'), 'panel_application', 'attendee_account', ['attendee_account_id'], ['id'])


def downgrade():
    op.drop_constraint(op.f('fk_panel_application_attendee_account_id_attendee_account'), 'panel_application', type_='foreignkey')
    op.drop_column('panel_application', 'attendee_account_id')
    op.drop_constraint(op.f('fk_mits_team_attendee_account_id_attendee_account'), 'mits_team', type_='foreignkey')
    op.drop_column('mits_team', 'attendee_account_id')
    op.drop_constraint(op.f('fk_indie_studio_attendee_account_id_attendee_account'), 'indie_studio', type_='foreignkey')
    op.drop_column('indie_studio', 'attendee_account_id')
