"""Add cost tracking and registered date for promo code groups

Revision ID: e0c620d341cb
Revises: 523e3d243395
Create Date: 2019-03-07 03:00:57.592885

"""


# revision identifiers, used by Alembic.
revision = 'e0c620d341cb'
down_revision = '523e3d243395'
branch_labels = None

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
    op.add_column('promo_code', sa.Column('cost', sa.Integer(), nullable=True))
    op.add_column('promo_code_group', sa.Column('registered', residue.UTCDateTime(), server_default=sa.text("timezone('utc', current_timestamp)"), nullable=False))


def downgrade():
    op.drop_column('promo_code_group', 'registered')
    op.drop_column('promo_code', 'cost')
