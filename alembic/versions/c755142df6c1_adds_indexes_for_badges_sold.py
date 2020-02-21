"""Adds indexes for BADGES_SOLD

Revision ID: c755142df6c1
Revises: 3733faf640e9
Create Date: 2017-07-26 01:40:26.647502

"""


# revision identifiers, used by Alembic.
revision = 'c755142df6c1'
down_revision = '3733faf640e9'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa



try:
    is_sqlite = op.get_context().dialect.name == 'sqlite'
except:
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
    if is_sqlite:
        with op.batch_alter_table('attendee', reflect_kwargs=sqlite_reflect_kwargs) as batch_op:
            batch_op.create_index(op.f('ix_attendee_badge_status'), ['badge_status'], unique=False)
            batch_op.create_index(op.f('ix_attendee_paid'), ['paid'], unique=False)
            batch_op.create_index('ix_attendee_paid_group_id', ['paid', 'group_id'], unique=False)

        with op.batch_alter_table('group', reflect_kwargs=sqlite_reflect_kwargs) as batch_op:
            batch_op.create_index(op.f('ix_group_amount_paid'), ['amount_paid'], unique=False)
    else:
        op.create_index(op.f('ix_attendee_badge_status'), 'attendee', ['badge_status'], unique=False)
        op.create_index(op.f('ix_attendee_paid'), 'attendee', ['paid'], unique=False)
        op.create_index('ix_attendee_paid_group_id', 'attendee', ['paid', 'group_id'], unique=False)
        op.create_index(op.f('ix_group_amount_paid'), 'group', ['amount_paid'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_group_amount_paid'), table_name='group')
    op.drop_index('ix_attendee_paid_group_id', table_name='attendee')
    op.drop_index(op.f('ix_attendee_paid'), table_name='attendee')
    op.drop_index(op.f('ix_attendee_badge_status'), table_name='attendee')
