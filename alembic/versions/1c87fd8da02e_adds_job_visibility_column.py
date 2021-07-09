"""Adds Job visibility column

Revision ID: 1c87fd8da02e
Revises: 735063d71b57
Create Date: 2017-12-13 12:18:59.551609

"""


# revision identifiers, used by Alembic.
revision = '1c87fd8da02e'
down_revision = '735063d71b57'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import table
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


dept_membership_request_table = table(
    'dept_membership_request',
    sa.Column('id', residue.UUID()),
    sa.Column('attendee_id', residue.UUID()),
    sa.Column('department_id', residue.UUID()),
)


def upgrade():
    if is_sqlite:
        with op.batch_alter_table('job', reflect_kwargs=sqlite_reflect_kwargs) as batch_op:
            batch_op.add_column(sa.Column('visibility', sa.Integer(), server_default='0', nullable=False))
            batch_op.create_index('ix_job_department_id', ['department_id'], unique=False)

        with op.batch_alter_table('dept_membership', reflect_kwargs=sqlite_reflect_kwargs) as batch_op:
            batch_op.create_index('ix_dept_membership_attendee_id', ['attendee_id'], unique=False)
            batch_op.create_index('ix_dept_membership_department_id', ['department_id'], unique=False)

        with op.batch_alter_table('dept_membership_dept_role', reflect_kwargs=sqlite_reflect_kwargs) as batch_op:
            batch_op.create_index('ix_dept_membership_dept_role_dept_membership_id', ['dept_membership_id'], unique=False)
            batch_op.create_index('ix_dept_membership_dept_role_dept_role_id', ['dept_role_id'], unique=False)

        with op.batch_alter_table('dept_membership_request', reflect_kwargs=sqlite_reflect_kwargs) as batch_op:
            batch_op.create_index('ix_dept_membership_request_attendee_id', ['attendee_id'], unique=False)
            batch_op.create_index('ix_dept_membership_request_department_id', ['department_id'], unique=False)

        with op.batch_alter_table('dept_role', reflect_kwargs=sqlite_reflect_kwargs) as batch_op:
            batch_op.create_index('ix_dept_role_department_id', ['department_id'], unique=False)

        with op.batch_alter_table('job_required_role', reflect_kwargs=sqlite_reflect_kwargs) as batch_op:
            batch_op.create_index('ix_job_required_role_dept_role_id', ['dept_role_id'], unique=False)
            batch_op.create_index('ix_job_required_role_job_id', ['job_id'], unique=False)

        with op.batch_alter_table('shift', reflect_kwargs=sqlite_reflect_kwargs) as batch_op:
            batch_op.create_index('ix_shift_attendee_id', ['attendee_id'], unique=False)
            batch_op.create_index('ix_shift_job_id', ['job_id'], unique=False)
    else:
        op.add_column('job', sa.Column('visibility', sa.Integer(), server_default='0', nullable=False))

        op.create_index('ix_job_department_id', 'job', ['department_id'], unique=False)
        op.create_index('ix_dept_membership_attendee_id', 'dept_membership', ['attendee_id'], unique=False)
        op.create_index('ix_dept_membership_department_id', 'dept_membership', ['department_id'], unique=False)
        op.create_index('ix_dept_membership_dept_role_dept_membership_id', 'dept_membership_dept_role', ['dept_membership_id'], unique=False)
        op.create_index('ix_dept_membership_dept_role_dept_role_id', 'dept_membership_dept_role', ['dept_role_id'], unique=False)
        op.create_index('ix_dept_membership_request_attendee_id', 'dept_membership_request', ['attendee_id'], unique=False)
        op.create_index('ix_dept_membership_request_department_id', 'dept_membership_request', ['department_id'], unique=False)
        op.create_index('ix_dept_role_department_id', 'dept_role', ['department_id'], unique=False)
        op.create_index('ix_job_required_role_dept_role_id', 'job_required_role', ['dept_role_id'], unique=False)
        op.create_index('ix_job_required_role_job_id', 'job_required_role', ['job_id'], unique=False)
        op.create_index('ix_shift_attendee_id', 'shift', ['attendee_id'], unique=False)
        op.create_index('ix_shift_job_id', 'shift', ['job_id'], unique=False)

    # Removes duplicate membership requests caused by a bug that would save a
    # new "Anywhere" membership request everytime an attendee record was saved.
    connection = op.get_bind()
    membership_requests = connection.execute(
        dept_membership_request_table.select().where(
            dept_membership_request_table.c.department_id == None
        )
    )

    attende_ids = set()
    for membership_request in membership_requests:
        if membership_request.attendee_id in attende_ids:
            op.execute(
                dept_membership_request_table.delete().where(
                    dept_membership_request_table.c.id == membership_request.id
                )
            )
        else:
            attende_ids.add(membership_request.attendee_id)


def downgrade():
    op.drop_column('job', 'visibility')
    op.drop_index('ix_shift_job_id', table_name='shift')
    op.drop_index('ix_shift_attendee_id', table_name='shift')
    op.drop_index('ix_job_required_role_job_id', table_name='job_required_role')
    op.drop_index('ix_job_required_role_dept_role_id', table_name='job_required_role')
    op.drop_index('ix_job_department_id', table_name='job')
    op.drop_index('ix_dept_role_department_id', table_name='dept_role')
    op.drop_index('ix_dept_membership_request_department_id', table_name='dept_membership_request')
    op.drop_index('ix_dept_membership_request_attendee_id', table_name='dept_membership_request')
    op.drop_index('ix_dept_membership_dept_role_dept_role_id', table_name='dept_membership_dept_role')
    op.drop_index('ix_dept_membership_dept_role_dept_membership_id', table_name='dept_membership_dept_role')
    op.drop_index('ix_dept_membership_department_id', table_name='dept_membership')
    op.drop_index('ix_dept_membership_attendee_id', table_name='dept_membership')
