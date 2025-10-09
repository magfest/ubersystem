"""Add visibility property to lottery entries

Revision ID: 4112406db1ae
Revises: 445fb71a63a3
Create Date: 2025-10-07 08:10:47.114414

"""


# revision identifiers, used by Alembic.
revision = '4112406db1ae'
down_revision = '445fb71a63a3'
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
    op.add_column('lottery_application', sa.Column('final_status_hidden', sa.Boolean(), server_default='True', nullable=False))
    op.add_column('lottery_application', sa.Column('booking_url_hidden', sa.Boolean(), server_default='True', nullable=False))


def downgrade():
    op.drop_column('lottery_application', 'final_status_hidden')
    op.drop_column('lottery_application', 'booking_url_hidden')
