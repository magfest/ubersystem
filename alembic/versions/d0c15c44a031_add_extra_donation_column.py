"""Add extra donation column

Revision ID: d0c15c44a031
Revises: c755142df6c1
Create Date: 2017-07-28 14:31:27.080065

"""


# revision identifiers, used by Alembic.
revision = 'd0c15c44a031'
down_revision = 'c755142df6c1'
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
    conn = op.get_bind()
    if is_sqlite:
        with op.batch_alter_table('attendee', reflect_kwargs=sqlite_reflect_kwargs) as batch_op:
            batch_op.add_column(sa.Column('extra_donation', sa.Integer(), server_default='0', nullable=False))
    else:
        # Because this column used to be in an event plugin, we check for its existence before making it
        exists = conn.execute("SELECT COLUMN_NAME FROM information_schema.columns where TABLE_NAME = 'attendee' and COLUMN_NAME = 'extra_donation'").fetchall()
        if not exists:
            op.add_column('attendee', sa.Column('extra_donation', sa.Integer(), server_default='0', nullable=False))


def downgrade():
    op.drop_column('attendee', 'extra_donation')
