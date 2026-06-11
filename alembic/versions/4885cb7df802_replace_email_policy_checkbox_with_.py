"""Replace email policy checkbox with selection

Revision ID: 4885cb7df802
Revises: e10edef8faac
Create Date: 2026-06-10 14:02:49.594201

"""


# revision identifiers, used by Alembic.
revision = '4885cb7df802'
down_revision = 'e10edef8faac'
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
    op.add_column('automated_email', sa.Column('default_policy', sa.Integer(), nullable=True))
    op.drop_column('automated_email', 'policy_permanent')
    op.add_column('email', sa.Column('status_text', sa.Unicode(), nullable=False, server_default=''))


def downgrade():
    op.add_column('automated_email', sa.Column('policy_permanent', sa.BOOLEAN(), server_default=sa.text('false'), autoincrement=False, nullable=False))
    op.drop_column('automated_email', 'default_policy')
    op.drop_column('email', 'status_text')
