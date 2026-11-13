"""Change transferability property

Revision ID: 0b870f921676
Revises: 217f28ecbe95
Create Date: 2026-10-29 18:27:51.592781

"""


# revision identifiers, used by Alembic.
revision = '0b870f921676'
down_revision = '217f28ecbe95'
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
    op.add_column('attendee', sa.Column('transferable', sa.Integer(), nullable=False, server_default='108415758'))

    op.execute("""
            UPDATE attendee
            SET transferable = CASE WHEN can_transfer THEN 91688121 ELSE 108415758 END
        """)

    op.drop_column('attendee', 'can_transfer')


def downgrade():
    op.add_column('attendee', sa.Column('can_transfer', sa.BOOLEAN(), server_default=sa.text('false'), autoincrement=False, nullable=False))
    op.drop_column('attendee', 'transferable')
