"""Added second_shirt column to the Attendee table

Revision ID: 06b9ad98e471
Revises: 7839740aa454
Create Date: 2017-11-22 22:06:03.196604
"""

# revision identifiers, used by Alembic.
revision = '06b9ad98e471'
down_revision = '7839740aa454'
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
    op.add_column('attendee', sa.Column('second_shirt', sa.Integer(), server_default='194196342', nullable=False))


def downgrade():
    op.drop_column('attendee', 'second_shirt')
