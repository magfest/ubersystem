"""Convert ribbon to a multichoice column.

Revision ID: 9359297269a8
Revises: 167243c0e86c
Create Date: 2017-07-21 09:18:38.444238

"""


# revision identifiers, used by Alembic.
revision = '9359297269a8'
down_revision = '063eeaf98c57'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import table


try:
    is_sqlite = op.get_context().dialect.name == 'sqlite'
except:
    is_sqlite = False

if is_sqlite:
    op.get_context().connection.execute('PRAGMA foreign_keys=ON;')
    utcnow_server_default = "(datetime('now', 'utc'))"
else:
    utcnow_server_default = "timezone('utc', current_timestamp)"

# We need this table in order to upgrade/downgrade the ribbon column
attendee = table(
    'attendee',
    sa.Column('ribbon', sa.Unicode())
)

def upgrade():
    op.alter_column('attendee', 'ribbon', type_=sa.Unicode(), server_default = '', nullable = False)

    op.execute(
        attendee
            .update()
            .where(attendee.c.ribbon == '154973361')
            .values({'ribbon': ''})
    )


def downgrade():
    op.execute(
        attendee
            .update()
            .where(attendee.c.ribbon == '')
            .values({'ribbon': 154973361})
    )

    op.execute(
        attendee
            .update()
            .where(attendee.c.ribbon.contains(','))
            .values({'ribbon': 154973361})
    )

    op.alter_column('attendee', 'ribbon', server_default=None, nullable=True)

    # Alembic doesn't appear to support "USING" but postgres needs it to cast a
    # string to an integer, so we have to use raw sql
    op.execute('ALTER TABLE attendee ALTER COLUMN ribbon TYPE integer'
               ' USING ribbon::integer')

    op.alter_column('attendee', 'ribbon', server_default='154973361', nullable=False)