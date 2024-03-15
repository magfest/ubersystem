"""Adds attendee.hotel_pin unique constraint

Revision ID: 116e5aad3a5c
Revises: 61734fcb2e72
Create Date: 2018-08-22 03:40:36.246934

"""


# revision identifiers, used by Alembic.
revision = '116e5aad3a5c'
down_revision = '61734fcb2e72'
branch_labels = None
depends_on = None

from alembic import op
import residue
import sqlalchemy as sa
from sqlalchemy import func
from sqlalchemy.sql import and_, table, select



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
    sa.Column('id', residue.UUID()),
    sa.Column('hotel_pin', sa.Unicode()),
)


def upgrade():
    if not is_sqlite:
        connection = op.get_bind()
        attendees = connection.execute(select([
            attendee_table.c.hotel_pin,
            func.count(attendee_table.c.id),
            func.array_agg(attendee_table.c.id),
        ]).where(and_(
            attendee_table.c.hotel_pin != None,
            attendee_table.c.hotel_pin != '',
        )).group_by(
            attendee_table.c.hotel_pin,
        ).having(
            func.count(attendee_table.c.id) > 1,
        ))
        for hotel_pin, count, ids in attendees:
            hotel_pin_template = '{{:0{}d}}{{}}'.format(len(str(count))) if count > 9 else '{}{}'

            for i, id in enumerate(ids):
                new_hotel_pin = hotel_pin_template.format(i, hotel_pin)
                connection.execute(
                    attendee_table.update().where(attendee_table.c.id == id).values({
                        'hotel_pin': new_hotel_pin,
                    })
                )

    op.create_unique_constraint(op.f('uq_attendee_hotel_pin'), 'attendee', ['hotel_pin'])


def downgrade():
    op.drop_constraint(op.f('uq_attendee_hotel_pin'), 'attendee', type_='unique')
