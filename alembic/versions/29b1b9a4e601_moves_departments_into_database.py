"""Moves departments into database

Revision ID: 29b1b9a4e601
Revises: 4947b38a18b1
Create Date: 2017-10-17 15:27:08.947357

"""


# revision identifiers, used by Alembic.
revision = '29b1b9a4e601'
down_revision = '4947b38a18b1'
branch_labels = None
depends_on = None

import uuid
from collections import defaultdict

import sideboard.lib.sa
import sqlalchemy as sa
from alembic import op
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


from uber.config import c

DEPT_HEAD_RIBBON_STR = str(c.DEPT_HEAD_RIBBON)
DEPARTMENT_NAMESPACE = uuid.UUID('fe0f168e-47fe-4ec9-ba66-6917613da7fd')

job_location_to_department_id = {i: str(uuid.uuid5(DEPARTMENT_NAMESPACE, str(i))) for i in c.JOB_LOCATIONS.keys()}
job_interests_to_department_id = {i: job_location_to_department_id[i] for i in c.JOB_INTERESTS.keys() if i in job_location_to_department_id}
department_id_to_job_location = {d: i for i, d in job_location_to_department_id.items()}


job_table = table(
    'job',
    sa.Column('id', sideboard.lib.sa.UUID()),
    sa.Column('location', sa.Unicode()),
    sa.Column('restricted', sa.Boolean()),
    sa.Column('department_id', sideboard.lib.sa.UUID()),
)


job_role_table = table(
    'job_role',
    sa.Column('id', sideboard.lib.sa.UUID()),
    sa.Column('name', sa.UnicodeText()),
    sa.Column('description', sa.UnicodeText()),
    sa.Column('department_id', sideboard.lib.sa.UUID()),
)


job_required_role_table = table(
    'job_required_role',
    sa.Column('job_id', sideboard.lib.sa.UUID(), ForeignKey('job.id')),
    sa.Column('job_role_id', sideboard.lib.sa.UUID(), ForeignKey('job_role.id')),
)


attendee_table = table(
    'attendee',
    sa.Column('id', sideboard.lib.sa.UUID()),
    sa.Column('first_name', sa.Unicode()),
    sa.Column('last_name', sa.Unicode()),
    sa.Column('assigned_depts', sa.Unicode()),
    sa.Column('trusted_depts', sa.Unicode()),
    sa.Column('requested_depts', sa.Unicode()),
    sa.Column('ribbon', sa.Unicode())
)


department_table = table(
    'department',
    sa.Column('id', sideboard.lib.sa.UUID()),
    sa.Column('name', sa.Unicode()),
    sa.Column('description', sa.Unicode()),
    sa.Column('accepts_volunteers', sa.Boolean()),
    sa.Column('is_shiftless', sa.Boolean()),
)


department_membership_table = table(
    'department_membership',
    sa.Column('id', sideboard.lib.sa.UUID()),
    sa.Column('is_dept_head', sa.Boolean()),
    sa.Column('gets_checklist', sa.Boolean()),
    sa.Column('attendee_id', sideboard.lib.sa.UUID(), ForeignKey('attendee.id')),
    sa.Column('department_id', sideboard.lib.sa.UUID(), ForeignKey('department.id')),
)


department_membership_request_table = table(
    'department_membership_request',
    sa.Column('attendee_id', sideboard.lib.sa.UUID(), ForeignKey('attendee.id')),
    sa.Column('department_id', sideboard.lib.sa.UUID(), ForeignKey('department.id')),
)


department_membership_job_role_table = table(
    'department_membership_job_role',
    sa.Column('department_membership_id', sideboard.lib.sa.UUID, ForeignKey('department_membership.id')),
    sa.Column('job_role_id', sideboard.lib.sa.UUID, ForeignKey('job_role.id')))


def _trusted_job_role_id(department_id):
    return str(uuid.uuid5(DEPARTMENT_NAMESPACE, department_id))


def _department_membership_id(department_id, attendee_id):
    return str(uuid.uuid5(DEPARTMENT_NAMESPACE, department_id + attendee_id))


def _upgrade_job_department_id():
    connection = op.get_bind()
    for value, name in c.JOB_LOCATIONS.items():
        department_id = job_location_to_department_id[value]
        op.execute(
            department_table.insert().values({
                'id': department_id,
                'name': name,
                'description': name,
                'accepts_volunteers': value in job_interests_to_department_id,
                'is_shiftless': value in c.SHIFTLESS_DEPTS
            })
        )
        op.execute(
            job_table.update().where(job_table.c.location == value).values({
                'department_id': department_id
            })
        )
        op.execute(
            job_table.update().where(job_table.c.restricted == True).values({
                'department_id': department_id
            })
        )

        trusted_job_role_id = _trusted_job_role_id(department_id)
        op.execute(
            job_role_table.insert().values({
                'id': trusted_job_role_id,
                'name': 'Trusted',
                'description': 'Staffers with a proven track record in "{}" are considered "Trusted"'.format(name),
                'department_id': department_id
            })
        )

        restricted_jobs = connection.execute(
            job_table.select().where(and_(
                job_table.c.restricted == True,
                job_table.c.location == value)
            )
        )
        for restricted_job in restricted_jobs:
            op.execute(
                job_required_role_table.insert().values({
                    'job_id': restricted_job.id,
                    'job_role_id': trusted_job_role_id
                })
            )


def _downgrade_job_department_id():
    connection = op.get_bind()
    jobs = connection.execute(job_table.select())
    for job in jobs:
        trusted_job_role_id = _trusted_job_role_id(job.department_id)
        is_restricted = not not connection.execute(
            job_required_role_table.select().where(and_(
                job_required_role_table.c.job_id == job.id,
                job_required_role_table.c.job_role_id == trusted_job_role_id
            ))
        )
        op.execute(
            job_table.update().where(job_table.c.id == job.id).values({
                'location': department_id_to_job_location[job.department_id],
                'restricted': is_restricted
            })
        )


def _upgrade_attendee_departments():
    connection = op.get_bind()
    attendees = connection.execute(attendee_table.select().where(or_(
        and_(
            attendee_table.c.assigned_depts != '',
            attendee_table.c.assigned_depts != None),
        and_(
            attendee_table.c.trusted_depts != '',
            attendee_table.c.trusted_depts != None),
        and_(
            attendee_table.c.requested_depts != '',
            attendee_table.c.requested_depts != None))))
    for attendee in attendees:
        is_dept_head = DEPT_HEAD_RIBBON_STR in attendee.ribbon

        trusted_depts = set(map(lambda s: int(s), attendee.trusted_depts.split(','))) \
            if attendee.trusted_depts else set()

        assigned_depts = (set(map(lambda s: int(s), attendee.assigned_depts.split(',')))
            if attendee.assigned_depts else set()).union(trusted_depts)

        for value in assigned_depts:
            department_id = job_location_to_department_id[value]
            attendee_id = str(attendee.id)
            department_membership_id = _department_membership_id(department_id, attendee_id)
            op.execute(
                department_membership_table.insert().values({
                    'id': department_membership_id,
                    'is_dept_head': is_dept_head,
                    'gets_checklist': is_dept_head,
                    'department_id': department_id,
                    'attendee_id': attendee_id
                })
            )

            if value in trusted_depts:
                op.execute(
                    department_membership_job_role_table.insert().values({
                        'department_membership_id': department_membership_id,
                        'job_role_id': _trusted_job_role_id(department_id)
                    })
                )


        requested_depts = set(map(lambda s: int(s), attendee.requested_depts.split(','))) \
            if attendee.requested_depts else set()

        for value in requested_depts:
            department_id = None if value in [c.ANYTHING, c.OTHER] else job_location_to_department_id[value]
            attendee_id = str(attendee.id)
            op.execute(
                department_membership_request_table.insert().values({
                    'department_id': department_id,
                    'attendee_id': attendee_id
                })
            )

        if is_dept_head:
            if isinstance(attendee.ribbon, int):
                values = {'ribbon': c.DEPT_HEAD_RIBBON}
            else:
                values = {'ribbon': ','.join(filter(lambda s: s != DEPT_HEAD_RIBBON_STR, attendee.ribbon.split(',')))}

            op.execute(
                attendee_table.update().where(attendee_table.c.id == attendee.id).values(values)
            )


def _downgrade_attendee_departments():
    connection = op.get_bind()

    attendee_ids = set()
    attendee_assigned_depts = defaultdict(set)
    attendee_trusted_depts = defaultdict(set)
    attendee_requested_depts = defaultdict(set)
    attendee_is_dept_head = defaultdict(lambda: False)

    department_memberships = connection.execute(department_membership_table.select())
    for department_membership in department_memberships:
        attendee_id = department_membership.attendee_id
        attendee_ids.add(attendee_id)
        location = department_id_to_job_location[department_membership.department_id]

        if department_membership.is_dept_head:
            attendee_is_dept_head[attendee_id] = True

        trusted_roles = op.execute(
            department_membership_job_role_table.select().where(and_(
                department_membership_job_role_table.c.department_membership_id == department_membership.id,
                department_membership_job_role_table.c.job_role_id == _trusted_job_role_id(department_membership.department_id)
            ))
        )
        if trusted_roles or department_membership.is_dept_head:
            attendee_trusted_depts[attendee_id].add(location)

        attendee_assigned_depts[attendee_id].add(location)

    department_membership_requests = connection.execute(department_membership_request_table.select())
    for department_membership_request in department_membership_requests:
        attendee_id = department_membership.attendee_id
        attendee_ids.add(attendee_id)
        location = department_id_to_job_location[department_membership.department_id]
        attendee_requested_depts[attendee_id].add(location)

    for attendee_id in attendee_ids:
        values = {}
        if attendee_is_dept_head[attendee_id]:
            attendees = connection.execute(attendee_table.select().where(attendee_table.c.id == attendee_id))
            for attendee in attendees:
                if isinstance(attendee.ribbon, int):
                    values['ribbon'] = c.DEPT_HEAD_RIBBON
                else:
                    values['ribbon'] = ','.join(str(attendee.ribbon).split(',') + [DEPT_HEAD_RIBBON_STR])

        values['trusted_depts'] = ','.join(map(str, attendee_trusted_depts[attendee_id]))
        values['assigned_depts'] = ','.join(map(str, attendee_assigned_depts[attendee_id]))
        values['requested_depts'] = ','.join(map(str, attendee_requested_depts[attendee_id]))

        op.execute(attendee_table.update().where(attendee_table.c.id == attendee_id).values(values))


def upgrade():
    op.create_table('department',
    sa.Column('id', sideboard.lib.sa.UUID(), nullable=False),
    sa.Column('name', sa.Unicode(), server_default='', nullable=False),
    sa.Column('description', sa.Unicode(), server_default='', nullable=False),
    sa.Column('accepts_volunteers', sa.Boolean(), server_default='True', nullable=False),
    sa.Column('is_shiftless', sa.Boolean(), server_default='False', nullable=False),
    sa.Column('parent_id', sideboard.lib.sa.UUID(), nullable=True),
    sa.ForeignKeyConstraint(['parent_id'], ['department.id'], name=op.f('fk_department_parent_id_department')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_department'))
    )
    op.create_table('job_role',
    sa.Column('id', sideboard.lib.sa.UUID(), nullable=False),
    sa.Column('name', sa.Unicode(), server_default='', nullable=False),
    sa.Column('description', sa.Unicode(), server_default='', nullable=False),
    sa.Column('department_id', sideboard.lib.sa.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['department_id'], ['department.id'], name=op.f('fk_job_role_department_id_department')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_job_role'))
    )
    op.create_table('department_membership',
    sa.Column('id', sideboard.lib.sa.UUID(), nullable=False),
    sa.Column('is_dept_head', sa.Boolean(), server_default='False', nullable=False),
    sa.Column('gets_checklist', sa.Boolean(), server_default='False', nullable=False),
    sa.Column('attendee_id', sideboard.lib.sa.UUID(), nullable=False),
    sa.Column('department_id', sideboard.lib.sa.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['attendee_id'], ['attendee.id'], name=op.f('fk_department_membership_attendee_id_attendee')),
    sa.ForeignKeyConstraint(['department_id'], ['department.id'], name=op.f('fk_department_membership_department_id_department')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_department_membership')),
    sa.UniqueConstraint('attendee_id', 'department_id', name=op.f('uq_department_membership_attendee_id'))
    )
    op.create_table('job_required_role',
    sa.Column('job_id', sideboard.lib.sa.UUID(), nullable=False),
    sa.Column('job_role_id', sideboard.lib.sa.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['job_id'], ['job.id'], name=op.f('fk_job_required_role_job_id_job')),
    sa.ForeignKeyConstraint(['job_role_id'], ['job_role.id'], name=op.f('fk_job_required_role_job_role_id_job_role'))
    )
    op.create_table('department_membership_request',
    sa.Column('attendee_id', sideboard.lib.sa.UUID(), nullable=False),
    sa.Column('department_id', sideboard.lib.sa.UUID(), nullable=True),
    sa.ForeignKeyConstraint(['attendee_id'], ['attendee.id'], name=op.f('fk_department_membership_request_attendee_id_attendee')),
    sa.ForeignKeyConstraint(['department_id'], ['department.id'], name=op.f('fk_department_membership_request_department_id_department')),
    sa.UniqueConstraint('attendee_id', 'department_id', name=op.f('uq_department_membership_request_attendee_id'))
    )
    op.create_table('department_membership_job_role',
    sa.Column('department_membership_id', sideboard.lib.sa.UUID(), nullable=False),
    sa.Column('job_role_id', sideboard.lib.sa.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['department_membership_id'], ['department_membership.id'], name=op.f('fk_department_membership_job_role_department_membership_id_department_membership')),
    sa.ForeignKeyConstraint(['job_role_id'], ['job_role.id'], name=op.f('fk_department_membership_job_role_job_role_id_job_role'))
    )

    if is_sqlite:
        with op.batch_alter_table('job', reflect_kwargs=sqlite_reflect_kwargs) as batch_op:
            batch_op.add_column(sa.Column('department_id', sideboard.lib.sa.UUID()))
    else:
        op.add_column('job', sa.Column('department_id', sideboard.lib.sa.UUID()))

    _upgrade_job_department_id()

    if is_sqlite:
        with op.batch_alter_table('job', reflect_kwargs=sqlite_reflect_kwargs) as batch_op:
            batch_op.alter_column('department_id', nullable=False)
            batch_op.drop_column('location')
            batch_op.drop_column('restricted')
            batch_op.create_foreign_key(op.f('fk_job_department_id_department'), 'department', ['department_id'], ['id'])
    else:
        op.alter_column('job', 'department_id', nullable=False)
        op.drop_column('job', 'location')
        op.drop_column('job', 'restricted')
        op.create_foreign_key(op.f('fk_job_department_id_department'), 'job', 'department', ['department_id'], ['id'])

    _upgrade_attendee_departments()

    if is_sqlite:
        with op.batch_alter_table('attendee', reflect_kwargs=sqlite_reflect_kwargs) as batch_op:
            batch_op.drop_column('trusted_depts')
            batch_op.drop_column('requested_depts')
            batch_op.drop_column('assigned_depts')
    else:
        op.drop_column('attendee', 'trusted_depts')
        op.drop_column('attendee', 'requested_depts')
        op.drop_column('attendee', 'assigned_depts')


def downgrade():
    if is_sqlite:
        with op.batch_alter_table('attendee', reflect_kwargs=sqlite_reflect_kwargs) as batch_op:
            batch_op.add_column(sa.Column('assigned_depts', sa.VARCHAR(), server_default=sa.text("''::character varying"), autoincrement=False, nullable=False))
            batch_op.add_column(sa.Column('requested_depts', sa.VARCHAR(), server_default=sa.text("''::character varying"), autoincrement=False, nullable=False))
            batch_op.add_column(sa.Column('trusted_depts', sa.VARCHAR(), server_default=sa.text("''::character varying"), autoincrement=False, nullable=False))
    else:
        op.add_column('attendee', sa.Column('assigned_depts', sa.VARCHAR(), server_default=sa.text("''::character varying"), autoincrement=False, nullable=False))
        op.add_column('attendee', sa.Column('requested_depts', sa.VARCHAR(), server_default=sa.text("''::character varying"), autoincrement=False, nullable=False))
        op.add_column('attendee', sa.Column('trusted_depts', sa.VARCHAR(), server_default=sa.text("''::character varying"), autoincrement=False, nullable=False))

    _downgrade_attendee_departments()

    if is_sqlite:
        with op.batch_alter_table('job', reflect_kwargs=sqlite_reflect_kwargs) as batch_op:
            batch_op.add_column(sa.Column('location', sa.INTEGER(), autoincrement=False))
            batch_op.add_column(sa.Column('restricted', sa.Boolean(), default=False, server_default='False', nullable=False))
            batch_op.drop_constraint(op.f('fk_job_department_id_department'), type_='foreignkey')
    else:
        op.add_column('job', sa.Column('location', sa.INTEGER(), autoincrement=False))
        op.add_column('job', sa.Column('restricted', sa.Boolean(), default=False, server_default='False', nullable=False))
        op.drop_constraint(op.f('fk_job_department_id_department'), 'job', type_='foreignkey')

    _downgrade_job_department_id()

    if is_sqlite:
        with op.batch_alter_table('job', reflect_kwargs=sqlite_reflect_kwargs) as batch_op:
            batch_op.alter_column('location', nullable=False)
            batch_op.drop_column('department_id')
    else:
        op.alter_column('job', 'location', nullable=False)
        op.drop_column('job', 'department_id')

    op.drop_table('department_membership_job_role')
    op.drop_table('department_membership_request')
    op.drop_table('job_required_role')
    op.drop_table('department_membership')
    op.drop_table('job_role')
    op.drop_table('department')
