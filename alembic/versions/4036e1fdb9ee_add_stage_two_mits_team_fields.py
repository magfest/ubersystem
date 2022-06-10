"""Add stage two MITS team fields

Revision ID: 4036e1fdb9ee
Revises: 26bc228319d2
Create Date: 2020-04-14 22:59:59.346742

"""


# revision identifiers, used by Alembic.
revision = '4036e1fdb9ee'
down_revision = '26bc228319d2'
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
    op.add_column('mits_team', sa.Column('concurrent_attendees', sa.Integer(), nullable=True))
    op.add_column('mits_team', sa.Column('days_available', sa.Integer(), nullable=True))
    op.add_column('mits_team', sa.Column('hours_available', sa.Integer(), nullable=True))


def downgrade():
    op.drop_column('mits_team', 'hours_available')
    op.drop_column('mits_team', 'days_available')
    op.drop_column('mits_team', 'concurrent_attendees')
