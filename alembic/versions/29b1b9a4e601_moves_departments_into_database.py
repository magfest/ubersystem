"""Moves departments into database

Revision ID: 29b1b9a4e601
Revises: e4d09d36083d
Create Date: 2017-10-17 15:27:08.947357

"""


# revision identifiers, used by Alembic.
revision = '29b1b9a4e601'
down_revision = 'e4d09d36083d'
branch_labels = None
depends_on = None

import uuid
from collections import defaultdict

import residue
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


from uber.config import c, create_namespace_uuid

DEPT_HEAD_RIBBON_STR = str(c.DEPT_HEAD_RIBBON)
DEPARTMENT_NAMESPACE = create_namespace_uuid('Department')


def _trusted_dept_role_id(department_id):
    return str(uuid.uuid5(DEPARTMENT_NAMESPACE, department_id))


def _dept_membership_id(department_id, attendee_id):
    return str(uuid.uuid5(DEPARTMENT_NAMESPACE, department_id + attendee_id))


def _dept_id_from_location(location):
    department_id = '{:07x}'.format(location) + str(uuid.uuid5(DEPARTMENT_NAMESPACE, str(location)))[7:]
    return department_id


def existing_location_from_dept_id(department_id):
    location = int(department_id[:7], 16)
    if job_location_to_department_id.get(location):
        return location
    return None


def single_dept_id_from_existing_locations(locations):
    for location in str(locations).split(','):
        if location:
            location = int(location)
            department_id = job_location_to_department_id.get(location)
            if department_id:
                return department_id
    return None


def all_dept_ids_from_existing_locations(locations):
    dept_ids = []
    for location in str(locations).split(','):
        if location:
            location = int(location)
            department_id = job_location_to_department_id.get(location)
            if department_id:
                dept_ids.append(department_id)
    return dept_ids


job_location_to_department_id = {i: _dept_id_from_location(i) for i in c.JOB_LOCATIONS.keys()}
job_interests_to_department_id = {i: job_location_to_department_id[i] for i in c.JOB_INTERESTS.keys() if i in job_location_to_department_id}


job_table = table(
    'job',
    sa.Column('id', residue.UUID()),
    sa.Column('location', sa.Unicode()),
    sa.Column('restricted', sa.Boolean()),
    sa.Column('department_id', residue.UUID()),
)


dept_role_table = table(
    'dept_role',
    sa.Column('id', residue.UUID()),
    sa.Column('name', sa.UnicodeText()),
    sa.Column('description', sa.UnicodeText()),
    sa.Column('department_id', residue.UUID()),
)


job_required_role_table = table(
    'job_required_role',
    sa.Column('job_id', residue.UUID(), ForeignKey('job.id')),
    sa.Column('dept_role_id', residue.UUID(), ForeignKey('dept_role.id')),
)


attendee_table = table(
    'attendee',
    sa.Column('id', residue.UUID()),
    sa.Column('first_name', sa.Unicode()),
    sa.Column('last_name', sa.Unicode()),
    sa.Column('assigned_depts', sa.Unicode()),
    sa.Column('trusted_depts', sa.Unicode()),
    sa.Column('requested_depts', sa.Unicode()),
    sa.Column('requested_any_dept', sa.Boolean()),
    sa.Column('ribbon', sa.Unicode())
)


department_table = table(
    'department',
    sa.Column('id', residue.UUID()),
    sa.Column('name', sa.Unicode()),
    sa.Column('description', sa.Unicode()),
    sa.Column('solicits_volunteers', sa.Boolean()),
    sa.Column('is_shiftless', sa.Boolean()),
)


dept_checklist_item_table = table(
    'dept_checklist_item',
    sa.Column('id', residue.UUID()),
    sa.Column('attendee_id', residue.UUID(), ForeignKey('attendee.id')),
    sa.Column('department_id', residue.UUID(), ForeignKey('department.id')),
    sa.Column('slug', sa.Unicode()),
    sa.Column('comments', sa.Unicode()),
)


dept_membership_table = table(
    'dept_membership',
    sa.Column('id', residue.UUID()),
    sa.Column('is_dept_head', sa.Boolean()),
    sa.Column('is_poc', sa.Boolean()),
    sa.Column('is_checklist_admin', sa.Boolean()),
    sa.Column('attendee_id', residue.UUID(), ForeignKey('attendee.id')),
    sa.Column('department_id', residue.UUID(), ForeignKey('department.id')),
)


dept_membership_request_table = table(
    'dept_membership_request',
    sa.Column('attendee_id', residue.UUID(), ForeignKey('attendee.id')),
    sa.Column('department_id', residue.UUID(), ForeignKey('department.id')),
)


dept_membership_dept_role_table = table(
    'dept_membership_dept_role',
    sa.Column('dept_membership_id', residue.UUID, ForeignKey('dept_membership.id')),
    sa.Column('dept_role_id', residue.UUID, ForeignKey('dept_role.id')))


def _upgrade_job_departments():
    connection = op.get_bind()
    for value, name in c.JOB_LOCATIONS.items():
        department_id = job_location_to_department_id[value]
        op.execute(
            department_table.insert().values({
                'id': department_id,
                'name': name,
                'description': name,
                'solicits_volunteers': value in job_interests_to_department_id,
                'is_shiftless': value in c.SHIFTLESS_DEPTS
            })
        )
        op.execute(
            job_table.update().where(job_table.c.location == value).values({
                'department_id': department_id
            })
        )

        trusted_dept_role_id = _trusted_dept_role_id(department_id)
        op.execute(
            dept_role_table.insert().values({
                'id': trusted_dept_role_id,
                'name': 'Trusted',
                'description': 'Staffers with a proven track record in the {} department can be considered "Trusted"'.format(name),
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
                    'dept_role_id': trusted_dept_role_id
                })
            )


def _downgrade_job_departments():
    connection = op.get_bind()
    jobs = connection.execute(job_table.select())
    for job in jobs:
        location = existing_location_from_dept_id(job.department_id)
        if location:
            trusted_dept_role_id = _trusted_dept_role_id(job.department_id)
            required_roles = connection.execute(
                job_required_role_table.select().where(and_(
                    job_required_role_table.c.job_id == job.id,
                    job_required_role_table.c.dept_role_id == trusted_dept_role_id
                ))
            )

            is_restricted = False
            for required_role in required_roles:
                is_restricted = True

            op.execute(
                job_table.update().where(job_table.c.id == job.id).values({
                    'location': location,
                    'restricted': is_restricted
                })
            )


def _upgrade_dept_checklist_items():
    connection = op.get_bind()
    items = connection.execute(dept_checklist_item_table.select())
    attendee_items = defaultdict(list)
    for item in items:
        attendee_items[item.attendee_id].append(item)
    for attendee_id, items in attendee_items.items():
        [attendee] = connection.execute(
            attendee_table.select().where(
                attendee_table.c.id == attendee_id
            )
        )
        dept_ids = all_dept_ids_from_existing_locations(attendee.assigned_depts)

        for item in items:
            if dept_ids:
                department_id = dept_ids[0]
                op.execute(
                    dept_checklist_item_table.update().where(dept_checklist_item_table.c.id == item.id).values({
                        'department_id': department_id
                    })
                )
                for department_id in dept_ids[1:]:
                    op.execute(
                        dept_checklist_item_table.insert().values({
                            'id': str(uuid.uuid4()),
                            'attendee_id': attendee_id,
                            'department_id': department_id,
                            'slug': item.slug,
                            'comments': item.comments,
                        })
                    )
            else:
                # Department doesn't exist, possibly bad location in assigned_depts
                op.execute(
                    dept_checklist_item_table.delete().where(
                        dept_checklist_item_table.c.id == item.id
                    )
                )


def _downgrade_dept_checklist_items():
    """
    This is an unfortunate situation, but if we ever decide to downgrade, we
    may be forced to delete some completed DeptChecklistItems. Under the old
    schema, department heads assigned to multiple departments could NOT
    complete any checklists. Furthermore, there was a unique constraint on
    dept_checklist_item(attendee_id, slug) which enforced that prohibition
    at the database level. In order to downgrade the scheme, we must delete
    any rows that violate that unique constraint.
    """
    connection = op.get_bind()
    duplicates = connection \
        .execute(func.array_agg(dept_checklist_item_table.c.id) \
        .select() \
        .group_by(dept_checklist_item_table.c.attendee_id, dept_checklist_item_table.c.slug) \
        .having(func.count() > 1))
    for duplicate_ids in duplicates:
        op.execute(
            dept_checklist_item_table.delete().where(
                dept_checklist_item_table.c.id.in_(duplicate_ids[0][1:])
            )
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

        trusted_depts = set(map(int, attendee.trusted_depts.split(','))) \
            if attendee.trusted_depts else set()

        assigned_depts = (set(map(int, attendee.assigned_depts.split(',')))
            if attendee.assigned_depts else set()).union(trusted_depts)

        for value in assigned_depts:
            department_id = single_dept_id_from_existing_locations(value)
            if department_id:
                attendee_id = str(attendee.id)
                dept_membership_id = _dept_membership_id(department_id, attendee_id)
                op.execute(
                    dept_membership_table.insert().values({
                        'id': dept_membership_id,
                        'is_dept_head': is_dept_head,
                        'is_poc': is_dept_head,
                        'is_checklist_admin': is_dept_head,
                        'department_id': department_id,
                        'attendee_id': attendee_id
                    })
                )

                if value in trusted_depts:
                    op.execute(
                        dept_membership_dept_role_table.insert().values({
                            'dept_membership_id': dept_membership_id,
                            'dept_role_id': _trusted_dept_role_id(department_id)
                        })
                    )

        requested_depts = set(map(int, attendee.requested_depts.split(','))) \
            if attendee.requested_depts else set()

        attendee_values = {}

        attendee_id = str(attendee.id)
        for value in requested_depts:
            department_id = single_dept_id_from_existing_locations(value)
            if department_id:
                op.execute(
                    dept_membership_request_table.insert().values({
                        'department_id': department_id,
                        'attendee_id': attendee_id
                    })
                )

            anywhere_values = []
            if getattr(c, 'ANYTHING', None) is not None:
                anywhere_values.append(c.ANYTHING)
            if getattr(c, 'OTHER', None) is not None:
                anywhere_values.append(c.OTHER)
            if value in anywhere_values:
                attendee_values['requested_any_dept'] = True

        if is_dept_head and assigned_depts:
            attendee_values['ribbon'] = ','.join(filter(lambda s: s != DEPT_HEAD_RIBBON_STR, attendee.ribbon.split(',')))

        if attendee_values:
            op.execute(
                attendee_table.update().where(attendee_table.c.id == attendee.id).values(attendee_values)
            )


def _downgrade_attendee_departments():
    connection = op.get_bind()

    attendee_ids = set()
    attendee_assigned_depts = defaultdict(set)
    attendee_trusted_depts = defaultdict(set)
    attendee_requested_depts = defaultdict(set)
    attendee_is_dept_head = defaultdict(lambda: False)

    dept_memberships = connection.execute(dept_membership_table.select())
    for dept_membership in dept_memberships:
        location = existing_location_from_dept_id(dept_membership.department_id)
        if location:
            attendee_id = dept_membership.attendee_id
            attendee_ids.add(attendee_id)

            if dept_membership.is_dept_head:
                attendee_is_dept_head[attendee_id] = True

            trusted_roles = op.execute(
                dept_membership_dept_role_table.select().where(and_(
                    dept_membership_dept_role_table.c.dept_membership_id == dept_membership.id,
                    dept_membership_dept_role_table.c.dept_role_id == _trusted_dept_role_id(dept_membership.department_id)
                ))
            )
            if trusted_roles or dept_membership.is_dept_head:
                attendee_trusted_depts[attendee_id].add(location)

            attendee_assigned_depts[attendee_id].add(location)

    dept_membership_requests = connection.execute(dept_membership_request_table.select())
    for dept_membership_request in dept_membership_requests:
        location = existing_location_from_dept_id(dept_membership_request.department_id)
        if location:
            attendee_id = dept_membership_request.attendee_id
            attendee_ids.add(attendee_id)
            attendee_requested_depts[attendee_id].add(location)

    for attendee_id in attendee_ids:
        values = {}
        if attendee_is_dept_head[attendee_id]:
            [attendee] = connection.execute(attendee_table.select().where(attendee_table.c.id == attendee_id))
            values['ribbon'] = ','.join(str(attendee.ribbon).split(',') + [DEPT_HEAD_RIBBON_STR])

        values['trusted_depts'] = ','.join(map(str, attendee_trusted_depts[attendee_id]))
        values['assigned_depts'] = ','.join(map(str, attendee_assigned_depts[attendee_id]))
        values['requested_depts'] = ','.join(map(str, attendee_requested_depts[attendee_id]))

        op.execute(attendee_table.update().where(attendee_table.c.id == attendee_id).values(values))

    if getattr(c, 'ANYTHING', None) is not None:
        op.execute(attendee_table.update().where(and_(
            attendee_table.c.requested_any_dept == True,
            attendee_table.c.requested_depts != '')).values({
            'requested_depts': func.concat(attendee_table.c.requested_depts, ',{}'.format(c.ANYTHING))
        }))

        op.execute(attendee_table.update().where(and_(
            attendee_table.c.requested_any_dept == True,
            attendee_table.c.requested_depts == '')).values({
            'requested_depts': str(c.ANYTHING)
        }))


def upgrade():
    op.create_table('department',
    sa.Column('id', residue.UUID(), nullable=False),
    sa.Column('name', sa.Unicode(), server_default='', nullable=False, unique=True),
    sa.Column('description', sa.Unicode(), server_default='', nullable=False),
    sa.Column('solicits_volunteers', sa.Boolean(), server_default='True', nullable=False),
    sa.Column('is_shiftless', sa.Boolean(), server_default='False', nullable=False),
    sa.Column('parent_id', residue.UUID(), nullable=True),
    sa.ForeignKeyConstraint(['parent_id'], ['department.id'], name=op.f('fk_department_parent_id_department')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_department'))
    )
    op.create_table('dept_role',
    sa.Column('id', residue.UUID(), nullable=False),
    sa.Column('name', sa.Unicode(), server_default='', nullable=False),
    sa.Column('description', sa.Unicode(), server_default='', nullable=False),
    sa.Column('department_id', residue.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['department_id'], ['department.id'], name=op.f('fk_dept_role_department_id_department')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_dept_role')),
    sa.UniqueConstraint('name', 'department_id', name=op.f('uq_dept_role_name'))
    )
    op.create_table('dept_membership',
    sa.Column('id', residue.UUID(), nullable=False),
    sa.Column('is_dept_head', sa.Boolean(), server_default='False', nullable=False),
    sa.Column('is_poc', sa.Boolean(), server_default='False', nullable=False),
    sa.Column('is_checklist_admin', sa.Boolean(), server_default='False', nullable=False),
    sa.Column('attendee_id', residue.UUID(), nullable=False),
    sa.Column('department_id', residue.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['attendee_id'], ['attendee.id'], name=op.f('fk_dept_membership_attendee_id_attendee')),
    sa.ForeignKeyConstraint(['department_id'], ['department.id'], name=op.f('fk_dept_membership_department_id_department')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_dept_membership')),
    sa.UniqueConstraint('attendee_id', 'department_id', name=op.f('uq_dept_membership_attendee_id'))
    )
    op.create_table('dept_membership_request',
    sa.Column('attendee_id', residue.UUID(), nullable=False),
    sa.Column('department_id', residue.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['attendee_id'], ['attendee.id'], name=op.f('fk_dept_membership_request_attendee_id_attendee')),
    sa.ForeignKeyConstraint(['department_id'], ['department.id'], name=op.f('fk_dept_membership_request_department_id_department')),
    sa.UniqueConstraint('attendee_id', 'department_id', name=op.f('uq_dept_membership_request_attendee_id'))
    )
    op.create_table('job_required_role',
    sa.Column('job_id', residue.UUID(), nullable=False),
    sa.Column('dept_role_id', residue.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['dept_role_id'], ['dept_role.id'], name=op.f('fk_job_required_role_dept_role_id_dept_role')),
    sa.ForeignKeyConstraint(['job_id'], ['job.id'], name=op.f('fk_job_required_role_job_id_job')),
    sa.UniqueConstraint('dept_role_id', 'job_id', name=op.f('uq_job_required_role_dept_role_id'))
    )
    op.create_table('dept_membership_dept_role',
    sa.Column('dept_membership_id', residue.UUID(), nullable=False),
    sa.Column('dept_role_id', residue.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['dept_membership_id'], ['dept_membership.id'], name=op.f('fk_dept_membership_dept_role_dept_membership_id_dept_membership')),
    sa.ForeignKeyConstraint(['dept_role_id'], ['dept_role.id'], name=op.f('fk_dept_membership_dept_role_dept_role_id_dept_role')),
    sa.UniqueConstraint('dept_membership_id', 'dept_role_id', name=op.f('uq_dept_membership_dept_role_dept_membership_id'))
    )

    if is_sqlite:
        with op.batch_alter_table('job', reflect_kwargs=sqlite_reflect_kwargs) as batch_op:
            batch_op.add_column(sa.Column('department_id', residue.UUID()))
        with op.batch_alter_table('dept_checklist_item', reflect_kwargs=sqlite_reflect_kwargs) as batch_op:
            batch_op.add_column(sa.Column('department_id', residue.UUID()))
            batch_op.drop_constraint('_dept_checklist_item_uniq', type_='unique')
        with op.batch_alter_table('attendee', reflect_kwargs=sqlite_reflect_kwargs) as batch_op:
            batch_op.add_column(sa.Column('requested_any_dept', sa.Boolean(), default=False, server_default='False', nullable=False))
    else:
        op.add_column('job', sa.Column('department_id', residue.UUID()))
        op.add_column('dept_checklist_item', sa.Column('department_id', residue.UUID()))
        op.drop_constraint('_dept_checklist_item_uniq', 'dept_checklist_item', type_='unique')
        op.add_column('attendee', sa.Column('requested_any_dept', sa.Boolean(), default=False, server_default='False', nullable=False))

    _upgrade_job_departments()
    _upgrade_dept_checklist_items()

    if is_sqlite:
        with op.batch_alter_table('job', reflect_kwargs=sqlite_reflect_kwargs) as batch_op:
            batch_op.alter_column('department_id', nullable=False)
            batch_op.drop_column('location')
            batch_op.drop_column('restricted')
            batch_op.create_foreign_key(op.f('fk_job_department_id_department'), 'department', ['department_id'], ['id'])

        with op.batch_alter_table('dept_checklist_item', reflect_kwargs=sqlite_reflect_kwargs) as batch_op:
            batch_op.alter_column('department_id', nullable=False)
            batch_op.create_unique_constraint(op.f('uq_dept_checklist_item_department_id'), ['department_id', 'attendee_id', 'slug'])
            batch_op.create_foreign_key(op.f('fk_dept_checklist_item_department_id_department'), 'department', ['department_id'], ['id'])
    else:
        op.alter_column('job', 'department_id', nullable=False)
        op.drop_column('job', 'location')
        op.drop_column('job', 'restricted')
        op.create_foreign_key(op.f('fk_job_department_id_department'), 'job', 'department', ['department_id'], ['id'])

        op.alter_column('dept_checklist_item', 'department_id', nullable=False)
        op.create_unique_constraint(op.f('uq_dept_checklist_item_department_id'), 'dept_checklist_item', ['department_id', 'attendee_id', 'slug'])
        op.create_foreign_key(op.f('fk_dept_checklist_item_department_id_department'), 'dept_checklist_item', 'department', ['department_id'], ['id'])

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

        with op.batch_alter_table('dept_checklist_item', reflect_kwargs=sqlite_reflect_kwargs) as batch_op:
            batch_op.drop_constraint(op.f('fk_dept_checklist_item_department_id_department'), type_='foreignkey')
    else:
        op.add_column('job', sa.Column('location', sa.INTEGER(), autoincrement=False))
        op.add_column('job', sa.Column('restricted', sa.Boolean(), default=False, server_default='False', nullable=False))
        op.drop_constraint(op.f('fk_job_department_id_department'), 'job', type_='foreignkey')

        op.drop_constraint(op.f('fk_dept_checklist_item_department_id_department'), 'dept_checklist_item', type_='foreignkey')

    _downgrade_job_departments()
    _downgrade_dept_checklist_items()

    if is_sqlite:
        with op.batch_alter_table('job', reflect_kwargs=sqlite_reflect_kwargs) as batch_op:
            batch_op.alter_column('location', nullable=False)
            batch_op.drop_column('department_id')

        with op.batch_alter_table('dept_checklist_item', reflect_kwargs=sqlite_reflect_kwargs) as batch_op:
            batch_op.create_unique_constraint('_dept_checklist_item_uniq', 'dept_checklist_item', ['attendee_id', 'slug'])
            batch_op.drop_constraint(op.f('uq_dept_checklist_item_department_id'), 'dept_checklist_item', type_='unique')
            batch_op.drop_column('department_id')

        with op.batch_alter_table('attendee', reflect_kwargs=sqlite_reflect_kwargs) as batch_op:
            batch_op.drop_column('requested_any_dept')
    else:
        op.alter_column('job', 'location', nullable=False)
        op.drop_column('job', 'department_id')

        op.create_unique_constraint('_dept_checklist_item_uniq', 'dept_checklist_item', ['attendee_id', 'slug'])
        op.drop_constraint(op.f('uq_dept_checklist_item_department_id'), 'dept_checklist_item', type_='unique')
        op.drop_column('dept_checklist_item', 'department_id')

        op.drop_column('attendee', 'requested_any_dept')

    op.drop_table('dept_membership_dept_role')
    op.drop_table('dept_membership_request')
    op.drop_table('job_required_role')
    op.drop_table('dept_membership')
    op.drop_table('dept_role')
    op.drop_table('department')
