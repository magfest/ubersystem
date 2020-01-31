"""Add electronic waiver to MITS

Revision ID: d1ae7f4f7767
Revises: 82e95f305078
Create Date: 2018-12-12 22:23:31.798569

"""


# revision identifiers, used by Alembic.
revision = 'd1ae7f4f7767'
down_revision = '82e95f305078'
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
    op.add_column('mits_team', sa.Column('waiver_signature', sa.Unicode(), server_default='', nullable=False))
    op.add_column('mits_team', sa.Column('waiver_signed', residue.UTCDateTime(), nullable=True))


def downgrade():
    op.drop_column('mits_team', 'waiver_signed')
    op.drop_column('mits_team', 'waiver_signature')
