"""Add support for attendee account password resets

Revision ID: a2e2e5eb9e3a
Revises: 1d2599479473
Create Date: 2021-09-10 00:28:42.211076

"""


# revision identifiers, used by Alembic.
revision = 'a2e2e5eb9e3a'
down_revision = '1d2599479473'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
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
    op.add_column('password_reset', sa.Column('admin_id', residue.UUID(), nullable=True))
    op.add_column('password_reset', sa.Column('attendee_id', residue.UUID(), nullable=True))
    op.create_unique_constraint(op.f('uq_password_reset_admin_id'), 'password_reset', ['admin_id'])
    op.create_unique_constraint(op.f('uq_password_reset_attendee_id'), 'password_reset', ['attendee_id'])
    op.drop_constraint('uq_password_reset_account_id', 'password_reset', type_='unique')
    op.drop_constraint('fk_password_reset_account_id_admin_account', 'password_reset', type_='foreignkey')
    op.create_foreign_key(op.f('fk_password_reset_admin_id_admin_account'), 'password_reset', 'admin_account', ['admin_id'], ['id'])
    op.create_foreign_key(op.f('fk_password_reset_attendee_id_attendee_account'), 'password_reset', 'attendee_account', ['attendee_id'], ['id'])
    op.drop_column('password_reset', 'account_id')


def downgrade():
    op.add_column('password_reset', sa.Column('account_id', postgresql.UUID(), autoincrement=False, nullable=False))
    op.drop_constraint(op.f('fk_password_reset_attendee_id_attendee_account'), 'password_reset', type_='foreignkey')
    op.drop_constraint(op.f('fk_password_reset_admin_id_admin_account'), 'password_reset', type_='foreignkey')
    op.create_foreign_key('fk_password_reset_account_id_admin_account', 'password_reset', 'admin_account', ['account_id'], ['id'])
    op.create_unique_constraint('uq_password_reset_account_id', 'password_reset', ['account_id'])
    op.drop_constraint(op.f('uq_password_reset_attendee_id'), 'password_reset', type_='unique')
    op.drop_constraint(op.f('uq_password_reset_admin_id'), 'password_reset', type_='unique')
    op.drop_column('password_reset', 'attendee_id')
    op.drop_column('password_reset', 'admin_id')
