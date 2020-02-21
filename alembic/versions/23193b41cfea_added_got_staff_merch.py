"""added Attendee.got_staff_merch column

Revision ID: 23193b41cfea
Revises: 5ae9cea2cd6d
Create Date: 2018-01-01 00:43:46.450809
"""
revision = '23193b41cfea'
down_revision = '5ae9cea2cd6d'
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


def upgrade():
    if is_sqlite:
        with op.batch_alter_table('attendee', reflect_kwargs=sqlite_reflect_kwargs) as batch_op:
            batch_op.add_column(sa.Column('got_staff_merch', sa.Boolean(), server_default='False', nullable=False))
    else:
        op.add_column('attendee', sa.Column('got_staff_merch', sa.Boolean(), server_default='False', nullable=False))


def downgrade():
    op.drop_column('attendee', 'got_staff_merch')
