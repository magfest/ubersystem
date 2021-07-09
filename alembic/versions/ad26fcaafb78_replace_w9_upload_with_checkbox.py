"""Replace W9 upload with checkbox

Revision ID: ad26fcaafb78
Revises: d42d4e52cfab
Create Date: 2019-11-19 01:10:46.057942

"""


# revision identifiers, used by Alembic.
revision = 'ad26fcaafb78'
down_revision = 'd42d4e52cfab'
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
    op.add_column('guest_taxes', sa.Column('w9_sent', sa.Boolean(), server_default='False', nullable=False))
    op.drop_column('guest_taxes', 'w9_content_type')
    op.drop_column('guest_taxes', 'w9_filename')


def downgrade():
    op.add_column('guest_taxes', sa.Column('w9_filename', sa.VARCHAR(), server_default=sa.text("''::character varying"), autoincrement=False, nullable=False))
    op.add_column('guest_taxes', sa.Column('w9_content_type', sa.VARCHAR(), server_default=sa.text("''::character varying"), autoincrement=False, nullable=False))
    op.drop_column('guest_taxes', 'w9_sent')
