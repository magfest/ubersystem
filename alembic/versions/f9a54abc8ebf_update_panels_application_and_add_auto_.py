"""Update panels application and add auto-waitlisting

Revision ID: f9a54abc8ebf
Revises: d606c3cb6b17
Create Date: 2022-08-27 23:33:19.296159

"""


# revision identifiers, used by Alembic.
revision = 'f9a54abc8ebf'
down_revision = 'd606c3cb6b17'
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
    op.add_column('panel_application', sa.Column('accepted', DateTime(), nullable=True))
    op.add_column('panel_application', sa.Column('confirmed', DateTime(), nullable=True))
    op.add_column('panel_application', sa.Column('department', sa.Integer(), server_default='39626696', nullable=False))
    op.add_column('panel_application', sa.Column('noise_level', sa.Integer(), nullable=False))
    op.add_column('panel_application', sa.Column('track', sa.Unicode(), server_default='', nullable=False))


def downgrade():
    op.drop_column('panel_application', 'track')
    op.drop_column('panel_application', 'noise_level')
    op.drop_column('panel_application', 'department')
    op.drop_column('panel_application', 'confirmed')
    op.drop_column('panel_application', 'accepted')
