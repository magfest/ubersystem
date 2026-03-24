"""Add SSO attendee accounts

Revision ID: f7f8a2662545
Revises: 4df6bfee2c69
Create Date: 2026-03-23 21:30:22.591600

"""


# revision identifiers, used by Alembic.
revision = 'f7f8a2662545'
down_revision = '4df6bfee2c69'
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
    op.add_column('admin_account', sa.Column('sso_id', sa.Unicode(), server_default='', nullable=False))
    op.add_column('attendee_account', sa.Column('sso_id', sa.Unicode(), server_default='', nullable=False))
    op.add_column('password_reset', sa.Column('token', sa.Unicode(), server_default='', nullable=False))


def downgrade():
    op.drop_column('password_reset', 'token')
    op.drop_column('attendee_account', 'sso_id')
    op.drop_column('admin_account', 'sso_id')
