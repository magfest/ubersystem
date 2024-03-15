"""Add separate MITS showcase scheduling column.

Revision ID: b574c0577253
Revises: 6c5cf22429e2
Create Date: 2018-09-26 19:29:40.149653

"""


# revision identifiers, used by Alembic.
revision = 'b574c0577253'
down_revision = '6c5cf22429e2'
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
    op.add_column('mits_times', sa.Column('showcase_availability', sa.Unicode(), server_default='', nullable=False))
    op.drop_column('mits_times', 'multiple_tables')


def downgrade():
    op.drop_column('mits_times', 'showcase_availability')
    op.add_column('mits_times', sa.Column('multiple_tables', sa.Unicode(), server_default='', nullable=False))
