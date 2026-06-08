"""Add current attendees to track imported attendees with their new badges

Revision ID: acbafbe2c23e
Revises: 4acd51ac5462
Create Date: 2022-07-17 07:59:04.242286

"""


# revision identifiers, used by Alembic.
revision = 'acbafbe2c23e'
down_revision = '4acd51ac5462'
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
    op.add_column('attendee', sa.Column('current_attendee_id', sa.Uuid(as_uuid=False), nullable=True))
    op.create_foreign_key(op.f('fk_attendee_current_attendee_id_attendee'), 'attendee', 'attendee', ['current_attendee_id'], ['id'])


def downgrade():
    op.drop_constraint(op.f('fk_attendee_current_attendee_id_attendee'), 'attendee', type_='foreignkey')
    op.drop_column('attendee', 'current_attendee_id')
