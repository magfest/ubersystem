"""Rename amount_paid and amount_refunded columns

Revision ID: 07f752ec9b7c
Revises: 3c0edc37569e
Create Date: 2019-08-28 22:58:09.649117

"""


# revision identifiers, used by Alembic.
revision = '07f752ec9b7c'
down_revision = '3c0edc37569e'
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
    op.alter_column('attendee', 'amount_refunded', new_column_name='amount_refunded_override')
    op.alter_column('attendee', 'amount_paid', new_column_name='amount_paid_override')
    op.alter_column('group', 'amount_refunded', new_column_name='amount_refunded_override')
    op.alter_column('group', 'amount_paid', new_column_name='amount_paid_override')
    op.create_index(op.f('ix_group_amount_paid_override'), 'group', ['amount_paid_override'], unique=False)
    op.drop_index('ix_group_amount_paid', table_name='group')


def downgrade():
    op.alter_column('attendee', 'amount_refunded_override', new_column_name='amount_refunded')
    op.alter_column('attendee', 'amount_paid_override', new_column_name='amount_paid')
    op.alter_column('group', 'amount_refunded_override', new_column_name='amount_refunded')
    op.alter_column('group', 'amount_paid_override', new_column_name='amount_paid')
    op.create_index('ix_group_amount_paid', 'group', ['amount_paid'], unique=False)
    op.drop_index(op.f('ix_group_amount_paid_override'), table_name='group')
