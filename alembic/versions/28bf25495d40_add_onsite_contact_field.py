"""Add onsite contact field

Revision ID: 28bf25495d40
Revises: 04826cecc42d
Create Date: 2022-09-28 17:51:03.712282

"""


# revision identifiers, used by Alembic.
revision = '28bf25495d40'
down_revision = '04826cecc42d'
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
    op.add_column('attendee', sa.Column('no_onsite_contact', sa.Boolean(), server_default='False', nullable=False))
    op.add_column('attendee', sa.Column('onsite_contact', sa.Unicode(), server_default='', nullable=False))


def downgrade():
    op.drop_column('attendee', 'onsite_contact')
    op.drop_column('attendee', 'no_onsite_contact')
