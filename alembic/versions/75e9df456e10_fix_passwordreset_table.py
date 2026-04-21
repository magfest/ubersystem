"""Fix PasswordReset table

Revision ID: 75e9df456e10
Revises: 116b5a9b66c1
Create Date: 2026-04-20 19:42:56.812344

"""


# revision identifiers, used by Alembic.
revision = '75e9df456e10'
down_revision = '116b5a9b66c1'
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
    op.alter_column('password_reset', 'admin_id',
               existing_type=sa.UUID(),
               nullable=True)
    op.alter_column('password_reset', 'attendee_id',
               existing_type=sa.UUID(),
               nullable=True)


def downgrade():
    op.alter_column('password_reset', 'attendee_id',
               existing_type=sa.UUID(),
               nullable=False)
    op.alter_column('password_reset', 'admin_id',
               existing_type=sa.UUID(),
               nullable=False)
