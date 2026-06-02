"""Add separate send_after date and last_signed_in

Revision ID: e10edef8faac
Revises: f0af7fedcf50
Create Date: 2026-05-28 08:59:35.011339

"""


# revision identifiers, used by Alembic.
revision = 'e10edef8faac'
down_revision = 'f0af7fedcf50'
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
    op.add_column('admin_account', sa.Column('last_signed_in', sa.DateTime(timezone=True), nullable=True))
    op.add_column('attendee_account', sa.Column('last_signed_in', sa.DateTime(timezone=True), nullable=True))
    op.add_column('email', sa.Column('send_after', sa.DateTime(timezone=True), nullable=True))
    op.add_column('automated_email', sa.Column('policy_permanent', sa.Boolean(), server_default='False', nullable=False))


def downgrade():
    op.drop_column('automated_email', 'policy_permanent')
    op.drop_column('email', 'send_after')
    op.drop_column('attendee_account', 'last_signed_in')
    op.drop_column('admin_account', 'last_signed_in')
