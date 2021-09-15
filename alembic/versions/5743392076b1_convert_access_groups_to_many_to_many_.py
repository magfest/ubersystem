"""Convert access groups to many-to-many relationship

Revision ID: 5743392076b1
Revises: 8888a0f4c1ef
Create Date: 2019-09-05 23:48:21.292758

"""


# revision identifiers, used by Alembic.
revision = '5743392076b1'
down_revision = '8888a0f4c1ef'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import residue
from sqlalchemy.schema import ForeignKey
from sqlalchemy.sql import table


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

admin_account = table(
    'admin_account',
    sa.Column('id', residue.UUID()),
    sa.Column('access_group_id', residue.UUID()),
)

access_group = table(
    'access_group',
    sa.Column('id', residue.UUID()),
    sa.Column('name', sa.Unicode()),
    sa.Column('access', sa.dialects.postgresql.json.JSONB()),
    sa.Column('read_only_access', sa.dialects.postgresql.json.JSONB()),
)

admin_access_group = table(
    'admin_access_group',
    sa.Column('admin_account_id', residue.UUID()),
    sa.Column('access_group_id', residue.UUID()),
)

def upgrade():
    op.create_table('admin_access_group',
    sa.Column('admin_account_id', residue.UUID(), nullable=False),
    sa.Column('access_group_id', residue.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['access_group_id'], ['access_group.id'], name=op.f('fk_admin_access_group_access_group_id_access_group')),
    sa.ForeignKeyConstraint(['admin_account_id'], ['admin_account.id'], name=op.f('fk_admin_access_group_admin_account_id_admin_account')),
    sa.UniqueConstraint('admin_account_id', 'access_group_id', name=op.f('uq_admin_access_group_admin_account_id'))
    )
    op.create_index('ix_admin_access_group_access_group_id', 'admin_access_group', ['access_group_id'], unique=False)
    op.create_index('ix_admin_access_group_admin_account_id', 'admin_access_group', ['admin_account_id'], unique=False)

    connection = op.get_bind()

    admin_attendees = connection.execute(admin_account.select())

    for attendee in admin_attendees:
        attendee_access_group = connection.execute(
            access_group.select().where(access_group.c.id == attendee.access_group_id)
        ).first()

        if attendee_access_group:
            connection.execute(
                admin_access_group.insert().values({
                    'admin_account_id': attendee.id,
                    'access_group_id': attendee_access_group.id,
                })
            )

    op.drop_constraint('fk_admin_account_access_group_id_access_group', 'admin_account', type_='foreignkey')
    op.drop_column('admin_account', 'access_group_id')


def downgrade():
    op.add_column('admin_account', sa.Column('access_group_id', postgresql.UUID(), autoincrement=False, nullable=True))
    op.create_foreign_key('fk_admin_account_access_group_id_access_group', 'admin_account', 'access_group',
                          ['access_group_id'], ['id'], ondelete='SET NULL')

    connection = op.get_bind()

    admin_attendees = connection.execute(admin_account.select())

    for attendee in admin_attendees:
        attendee_access_group = connection.execute(
            admin_access_group.select().where(admin_access_group.c.admin_account_id == attendee.id)
        ).first()

        if attendee_access_group:
            connection.execute(
                admin_account.update()
                    .where(admin_account.c.id == attendee.id)
                    .values({'access_group_id': attendee_access_group.access_group_id})
            )

    op.drop_index('ix_admin_access_group_admin_account_id', table_name='admin_access_group')
    op.drop_index('ix_admin_access_group_access_group_id', table_name='admin_access_group')
    op.drop_table('admin_access_group')

