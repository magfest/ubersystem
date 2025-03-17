"""Add more social media columns for bands

Revision ID: 0a67e2307492
Revises: c7a439f29c1c
Create Date: 2022-06-21 00:28:42.008670

"""


# revision identifiers, used by Alembic.
revision = '0a67e2307492'
down_revision = 'c7a439f29c1c'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


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
    op.add_column('guest_bio', sa.Column('bandcamp', sa.Unicode(), server_default='', nullable=False))
    op.add_column('guest_bio', sa.Column('discord', sa.Unicode(), server_default='', nullable=False))
    op.add_column('guest_bio', sa.Column('instagram', sa.Unicode(), server_default='', nullable=False))
    op.add_column('guest_bio', sa.Column('twitch', sa.Unicode(), server_default='', nullable=False))


def downgrade():
    op.drop_column('guest_bio', 'twitch')
    op.drop_column('guest_bio', 'instagram')
    op.drop_column('guest_bio', 'discord')
    op.drop_column('guest_bio', 'bandcamp')
