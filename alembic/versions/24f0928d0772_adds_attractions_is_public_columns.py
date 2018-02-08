"""Adds attractions is_public columns

Revision ID: 24f0928d0772
Revises: fe5f87b292b4
Create Date: 2017-12-18 22:32:06.452742

"""


# revision identifiers, used by Alembic.
revision = '24f0928d0772'
down_revision = 'fe5f87b292b4'
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
    if is_sqlite:
        with op.batch_alter_table('attraction', reflect_kwargs=sqlite_reflect_kwargs) as batch_op:
            batch_op.add_column(sa.Column('is_public', sa.Boolean(), server_default='False', nullable=False))
        with op.batch_alter_table('attraction_feature', reflect_kwargs=sqlite_reflect_kwargs) as batch_op:
            batch_op.add_column(sa.Column('is_public', sa.Boolean(), server_default='False', nullable=False))
    else:
        op.add_column('attraction', sa.Column('is_public', sa.Boolean(), server_default='False', nullable=False))
        op.add_column('attraction_feature', sa.Column('is_public', sa.Boolean(), server_default='False', nullable=False))


def downgrade():
    op.drop_column('attraction_feature', 'is_public')
    op.drop_column('attraction', 'is_public')
