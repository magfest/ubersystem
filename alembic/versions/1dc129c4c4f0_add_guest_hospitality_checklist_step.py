"""Add guest hospitality checklist step

Revision ID: 1dc129c4c4f0
Revises: 3ec57493ad18
Create Date: 2023-10-13 00:56:43.772894

"""


# revision identifiers, used by Alembic.
revision = '1dc129c4c4f0'
down_revision = '3ec57493ad18'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa
from sqlalchemy.types import UUID


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
    op.create_table('guest_hospitality',
        sa.Column('id', UUID(), nullable=False),
        sa.Column('guest_id', UUID(), nullable=False),
        sa.Column('completed', sa.Boolean(), server_default='False', nullable=False),
        sa.ForeignKeyConstraint(['guest_id'], ['guest_group.id'], name=op.f('fk_guest_hospitality_guest_id_guest_group')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_guest_hospitality')),
        sa.UniqueConstraint('guest_id', name=op.f('uq_guest_hospitality_guest_id'))
    )


def downgrade():
    op.drop_table('guest_hospitality')
