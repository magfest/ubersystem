"""Set creator ID null on delete

Revision ID: 96605e65d7a8
Revises: 18b32eb66908
Create Date: 2025-06-04 16:34:14.118167

"""


# revision identifiers, used by Alembic.
revision = '96605e65d7a8'
down_revision = '18b32eb66908'
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
    op.drop_constraint('fk_attendee_creator_id_attendee', 'attendee', type_='foreignkey')
    op.create_foreign_key(op.f('fk_attendee_creator_id_attendee'), 'attendee', 'attendee', ['creator_id'], ['id'], ondelete='set null')


def downgrade():
    op.drop_constraint(op.f('fk_attendee_creator_id_attendee'), 'attendee', type_='foreignkey')
    op.create_foreign_key('fk_attendee_creator_id_attendee', 'attendee', 'attendee', ['creator_id'], ['id'])
