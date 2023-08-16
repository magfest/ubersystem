"""Add new fields to panel applications

Revision ID: 1fcbcf875d8e
Revises: c31a2e5b6fbd
Create Date: 2023-08-08 07:19:53.147625

"""


# revision identifiers, used by Alembic.
revision = '1fcbcf875d8e'
down_revision = 'c31a2e5b6fbd'
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
    with op.batch_alter_table("panel_applicant") as batch_op:
        batch_op.add_column(sa.Column('display_name', sa.Unicode(), server_default='', nullable=False))
        batch_op.add_column(sa.Column('guidebook_bio', sa.Unicode(), server_default='', nullable=False))
    
    with op.batch_alter_table("panel_application") as batch_op:
        batch_op.add_column(sa.Column('granular_rating', sa.Unicode(), server_default='', nullable=False))


def downgrade():
    op.drop_column('panel_application', 'granular_rating')
    op.drop_column('panel_applicant', 'guidebook_bio')
    op.drop_column('panel_applicant', 'display_name')
