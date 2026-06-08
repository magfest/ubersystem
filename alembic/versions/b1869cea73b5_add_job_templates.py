"""Add job templates

Revision ID: b1869cea73b5
Revises: 5ff34b22e1bc
Create Date: 2025-11-01 21:40:24.888292

"""


# revision identifiers, used by Alembic.
revision = 'b1869cea73b5'
down_revision = '5ff34b22e1bc'
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
    op.create_table('job_template',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('created', sa.DateTime(timezone=True), server_default=sa.text("timezone('utc', current_timestamp)"), nullable=False),
    sa.Column('last_updated', sa.DateTime(timezone=True), server_default=sa.text("timezone('utc', current_timestamp)"), nullable=False),
    sa.Column('external_id', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('last_synced', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('department_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('template_name', sa.Unicode(), server_default='', nullable=False),
    sa.Column('type', sa.Integer(), server_default='94737193', nullable=False),
    sa.Column('name', sa.Unicode(), server_default='', nullable=False),
    sa.Column('description', sa.Unicode(), server_default='', nullable=False),
    sa.Column('duration', sa.Integer(), nullable=False),
    sa.Column('weight', sa.Float(), server_default='1', nullable=False),
    sa.Column('extra15', sa.Boolean(), server_default='False', nullable=False),
    sa.Column('visibility', sa.Integer(), server_default='0', nullable=False),
    sa.Column('all_roles_required', sa.Boolean(), server_default='True', nullable=False),
    sa.Column('min_slots', sa.Integer(), nullable=False),
    sa.Column('days', sa.Unicode(), server_default='', nullable=False),
    sa.Column('open_time', sa.Time(), nullable=True),
    sa.Column('close_time', sa.Time(), nullable=True),
    sa.Column('interval', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['department_id'], ['department.id'], name=op.f('fk_job_template_department_id_department')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_job_template'))
    )
    op.create_table('job_template_required_role',
    sa.Column('dept_role_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('job_template_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.ForeignKeyConstraint(['dept_role_id'], ['dept_role.id'], name=op.f('fk_job_template_required_role_dept_role_id_dept_role')),
    sa.ForeignKeyConstraint(['job_template_id'], ['job_template.id'], name=op.f('fk_job_template_required_role_job_template_id_job_template')),
    sa.UniqueConstraint('dept_role_id', 'job_template_id', name=op.f('uq_job_template_required_role_dept_role_id'))
    )
    op.create_index('ix_job_template_required_role_dept_role_id', 'job_template_required_role', ['dept_role_id'], unique=False)
    op.create_index('ix_job_template_required_role_job_template_id', 'job_template_required_role', ['job_template_id'], unique=False)
    op.drop_column('department', 'is_teardown_approval_exempt')
    op.drop_column('department', 'is_setup_approval_exempt')
    op.drop_column('department', 'is_shiftless')
    op.add_column('job', sa.Column('job_template_id', sa.Uuid(as_uuid=False), nullable=True))
    op.add_column('job', sa.Column('all_roles_required', sa.Boolean(), server_default='True', nullable=False))
    op.create_foreign_key(op.f('fk_job_job_template_id_job_template'), 'job', 'job_template', ['job_template_id'], ['id'])
    op.drop_column('job', 'type')


def downgrade():
    op.add_column('job', sa.Column('type', sa.INTEGER(), server_default=sa.text('252034462'), autoincrement=False, nullable=False))
    op.drop_constraint(op.f('fk_job_job_template_id_job_template'), 'job', type_='foreignkey')
    op.drop_column('job', 'all_roles_required')
    op.drop_column('job', 'job_template_id')
    op.add_column('department', sa.Column('is_shiftless', sa.BOOLEAN(), server_default=sa.text('false'), autoincrement=False, nullable=False))
    op.add_column('department', sa.Column('is_setup_approval_exempt', sa.BOOLEAN(), server_default=sa.text('false'), autoincrement=False, nullable=False))
    op.add_column('department', sa.Column('is_teardown_approval_exempt', sa.BOOLEAN(), server_default=sa.text('false'), autoincrement=False, nullable=False))
    op.drop_index('ix_job_template_required_role_job_template_id', table_name='job_template_required_role')
    op.drop_index('ix_job_template_required_role_dept_role_id', table_name='job_template_required_role')
    op.drop_table('job_template_required_role')
    op.drop_table('job_template')
