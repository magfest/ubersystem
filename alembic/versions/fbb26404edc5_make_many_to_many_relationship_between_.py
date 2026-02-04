"""Make many-to-many relationship between panel applications and applicants

Revision ID: fbb26404edc5
Revises: 96605e65d7a8
Create Date: 2025-05-26 22:10:30.926854

"""


# revision identifiers, used by Alembic.
revision = 'fbb26404edc5'
down_revision = '96605e65d7a8'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


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
    op.create_table('panel_applicant_application',
    sa.Column('panel_applicant_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('panel_application_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.ForeignKeyConstraint(['panel_applicant_id'], ['panel_applicant.id'], name=op.f('fk_panel_applicant_application_panel_applicant_id_panel_applicant')),
    sa.ForeignKeyConstraint(['panel_application_id'], ['panel_application.id'], name=op.f('fk_panel_applicant_application_panel_application_id_panel_application')),
    sa.UniqueConstraint('panel_applicant_id', 'panel_application_id', name=op.f('uq_panel_applicant_application_panel_applicant_id'))
    )
    op.create_index('ix_admin_panel_application_panel_applicant_id', 'panel_applicant_application', ['panel_applicant_id'], unique=False)
    op.create_index('ix_admin_panel_application_panel_application_id', 'panel_applicant_application', ['panel_application_id'], unique=False)
    op.drop_constraint('fk_panel_applicant_app_id_panel_application', 'panel_applicant', type_='foreignkey')
    op.drop_column('panel_applicant', 'app_id')
    op.add_column('panel_application', sa.Column('submitter_id', sa.Uuid(as_uuid=False), nullable=True))
    op.create_foreign_key(op.f('fk_panel_application_submitter_id_panel_applicant'), 'panel_application', 'panel_applicant', ['submitter_id'], ['id'], ondelete='SET NULL')


def downgrade():
    op.drop_constraint(op.f('fk_panel_application_submitter_id_panel_applicant'), 'panel_application', type_='foreignkey')
    op.drop_column('panel_application', 'submitter_id')
    op.add_column('panel_applicant', sa.Column('app_id', postgresql.UUID(), autoincrement=False, nullable=False))
    op.create_foreign_key('fk_panel_applicant_app_id_panel_application', 'panel_applicant', 'panel_application', ['app_id'], ['id'], ondelete='CASCADE')
    op.drop_index('ix_admin_panel_application_panel_application_id', table_name='panel_applicant_application')
    op.drop_index('ix_admin_panel_application_panel_applicant_id', table_name='panel_applicant_application')
    op.drop_table('panel_applicant_application')
