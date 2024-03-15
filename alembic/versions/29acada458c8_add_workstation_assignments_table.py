"""Add workstation assignments table

Revision ID: 29acada458c8
Revises: 6af647ca7d1f
Create Date: 2023-11-15 02:06:35.804619

"""


# revision identifiers, used by Alembic.
revision = '29acada458c8'
down_revision = '6af647ca7d1f'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa
import residue


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
    op.create_table('workstation_assignment',
    sa.Column('id', residue.UUID(), nullable=False),
    sa.Column('reg_station_id', sa.Integer(), nullable=False),
    sa.Column('printer_id', sa.Unicode(), server_default='', nullable=False),
    sa.Column('minor_printer_id', sa.Unicode(), server_default='', nullable=False),
    sa.Column('terminal_id', sa.Unicode(), server_default='', nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_workstation_assignments'))
    )


def downgrade():
    op.drop_table('workstation_assignment')
