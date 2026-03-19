"""Drops requested_any_dept column

Revision ID: d3da548acd2e
Revises: 29b1b9a4e601
Create Date: 2017-11-06 09:33:21.963533

"""


# revision identifiers, used by Alembic.
revision = 'd3da548acd2e'
down_revision = '29b1b9a4e601'
branch_labels = None
depends_on = None


import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy import func
from sqlalchemy.schema import ForeignKey
from sqlalchemy.sql import and_, or_, table


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


attendee_table = table(
    'attendee',
    sa.Column('id', sa.Uuid(as_uuid=False)),
    sa.Column('requested_any_dept', sa.Boolean()),
)


dept_membership_request_table = table(
    'dept_membership_request',
    sa.Column('id', sa.Uuid(as_uuid=False)),
    sa.Column('attendee_id', sa.Uuid(as_uuid=False), ForeignKey('attendee.id')),
    sa.Column('department_id', sa.Uuid(as_uuid=False), ForeignKey('department.id')),
)


def upgrade():
    if is_sqlite:
        with op.batch_alter_table('dept_membership_request', reflect_kwargs=sqlite_reflect_kwargs) as batch_op:
            batch_op.add_column(sa.Column('id', sa.Uuid(as_uuid=False), nullable=True))
            batch_op.alter_column('department_id', existing_type=sa.Uuid(as_uuid=False), nullable=True)
    else:
        op.add_column('dept_membership_request', sa.Column('id', sa.Uuid(as_uuid=False), nullable=True))
        op.alter_column('dept_membership_request', 'department_id', existing_type=sa.Uuid(as_uuid=False), nullable=True)

    connection = op.get_bind()
    all_requests = connection.execute(dept_membership_request_table.select())
    for request in all_requests:
        connection.execute(
            dept_membership_request_table.update().where(and_(
                dept_membership_request_table.c.attendee_id == request.attendee_id,
                dept_membership_request_table.c.department_id == request.department_id
            )).values({
                'id': str(uuid.uuid4())
            })
        )

    attendees_requesting_any = connection.execute(attendee_table.select().where(
        attendee_table.c.requested_any_dept == True
    ))
    for attendee in attendees_requesting_any:
        connection.execute(
            dept_membership_request_table.insert().values({
                'id': str(uuid.uuid4()),
                'attendee_id': attendee.id,
                'department_id': None
            })
        )

    if is_sqlite:
        with op.batch_alter_table('dept_membership_request', reflect_kwargs=sqlite_reflect_kwargs) as batch_op:
            batch_op.alter_column('id', existing_type=sa.Uuid(as_uuid=False), nullable=False)
            batch_op.create_primary_key('pk_dept_membership_request', ['id', ])
        with op.batch_alter_table('attendee', reflect_kwargs=sqlite_reflect_kwargs) as batch_op:
            batch_op.drop_column('requested_any_dept')
    else:
        op.alter_column('dept_membership_request', 'id', existing_type=sa.Uuid(as_uuid=False), nullable=False)
        op.create_primary_key('pk_dept_membership_request', 'dept_membership_request', ['id', ])
        op.drop_column('attendee', 'requested_any_dept')


def downgrade():
    if is_sqlite:
        with op.batch_alter_table('attendee', reflect_kwargs=sqlite_reflect_kwargs) as batch_op:
            batch_op.add_column(sa.Column('requested_any_dept', sa.BOOLEAN(), server_default=sa.text('false'), autoincrement=False, nullable=False))
    else:
        op.add_column('attendee', sa.Column('requested_any_dept', sa.BOOLEAN(), server_default=sa.text('false'), autoincrement=False, nullable=False))

    connection = op.get_bind()
    requests_for_any = connection.execute(dept_membership_request_table.select().where(
        dept_membership_request_table.c.department_id == None))
    for request in requests_for_any:
        connection.execute(
            attendee_table.update().where(attendee_table.c.id == request.attendee_id).values({
                'requested_any_dept': True
            })
        )

    connection.execute(
        dept_membership_request_table.delete().where(
            dept_membership_request_table.c.department_id == None
        )
    )

    if is_sqlite:
        with op.batch_alter_table('dept_membership_request', reflect_kwargs=sqlite_reflect_kwargs) as batch_op:
            batch_op.drop_column('id')
            batch_op.alter_column('department_id', existing_type=sa.Uuid(as_uuid=False), nullable=False)
    else:
        op.drop_column('dept_membership_request', 'id')
        op.alter_column('dept_membership_request', 'department_id', existing_type=sa.Uuid(as_uuid=False), nullable=False)
