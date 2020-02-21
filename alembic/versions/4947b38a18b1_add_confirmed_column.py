"""Add confirmed column

Revision ID: 4947b38a18b1
Revises: 6aef7396c197
Create Date: 2017-08-06 12:48:43.186696

"""


# revision identifiers, used by Alembic.
revision = '4947b38a18b1'
down_revision = '6aef7396c197'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa
import residue


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
    if is_sqlite:
        with op.batch_alter_table('attendee', reflect_kwargs=sqlite_reflect_kwargs) as batch_op:
            batch_op.add_column(sa.Column('confirmed', residue.UTCDateTime(), nullable=True))
    else:
        op.add_column('attendee', sa.Column('confirmed', residue.UTCDateTime(), nullable=True))


def downgrade():
    op.drop_column('attendee', 'confirmed')
