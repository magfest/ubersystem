"""Add MIVS to attendee relationship

Revision ID: 9b657ae4c4ac
Revises: 318d761a5c62
Create Date: 2024-10-07 20:53:07.005134

"""


# revision identifiers, used by Alembic.
revision = '9b657ae4c4ac'
down_revision = '318d761a5c62'
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
    op.add_column('indie_developer', sa.Column('attendee_id', residue.UUID(), nullable=True))
    op.create_unique_constraint(op.f('uq_indie_developer_attendee_id'), 'indie_developer', ['attendee_id'])
    op.create_foreign_key(op.f('fk_indie_developer_attendee_id_attendee'), 'indie_developer', 'attendee', ['attendee_id'], ['id'])


def downgrade():
    op.drop_constraint(op.f('fk_indie_developer_attendee_id_attendee'), 'indie_developer', type_='foreignkey')
    op.drop_constraint(op.f('uq_indie_developer_attendee_id'), 'indie_developer', type_='unique')
    op.drop_column('indie_developer', 'attendee_id')
