"""Remove cascade from panel applicants

Revision ID: f6dc67fe7eea
Revises: ebf8fdbfc585
Create Date: 2024-12-15 17:21:24.568169

"""


# revision identifiers, used by Alembic.
revision = 'f6dc67fe7eea'
down_revision = 'ebf8fdbfc585'
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
    op.drop_constraint('fk_panel_applicant_attendee_id_attendee', 'panel_applicant', type_='foreignkey')
    op.create_foreign_key(op.f('fk_panel_applicant_attendee_id_attendee'), 'panel_applicant', 'attendee', ['attendee_id'], ['id'], ondelete='SET NULL')


def downgrade():
    op.drop_constraint(op.f('fk_panel_applicant_attendee_id_attendee'), 'panel_applicant', type_='foreignkey')
    op.create_foreign_key('fk_panel_applicant_attendee_id_attendee', 'panel_applicant', 'attendee', ['attendee_id'], ['id'], ondelete='CASCADE')
