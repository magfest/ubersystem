"""Remove access column from admin accounts

Revision ID: 2cd71c52889e
Revises: 5ca0661d5081
Create Date: 2019-08-22 15:05:58.532275

"""


# revision identifiers, used by Alembic.
revision = '2cd71c52889e'
down_revision = '5ca0661d5081'
branch_labels = None
depends_on = None

from alembic import op
import residue
import sqlalchemy as sa
from sqlalchemy.sql import table
from uber.config import c
import uuid


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
    sa.Column('access_group_id', residue.UUID()),
    sa.Column('access', sa.Unicode()),
)

access_group = table(
    'access_group',
    sa.Column('id', residue.UUID()),
    sa.Column('name', sa.Unicode()),
    sa.Column('access', sa.dialects.postgresql.json.JSONB()),
    sa.Column('read_only_access', sa.dialects.postgresql.json.JSONB()),
)

def upgrade():
    all_access = {section: '5' for section in c.ADMIN_PAGES}
    access_group_id = uuid.uuid4()
    connection = op.get_bind()

    connection.execute(
        access_group.insert().values({
                'id': access_group_id,
                'name': "All Access",
                'access': all_access,
                'read_only_access': {},
            }),
    )

    connection.execute(
        admin_account.update()
            .where(admin_account.c.access.like('%37271822%'))
            .values({'access_group_id': access_group_id})
    )

    op.drop_column('admin_account', 'access')


def downgrade():
    op.add_column('admin_account', sa.Column('access', sa.VARCHAR(), server_default=sa.text("''::character varying"), autoincrement=False, nullable=False))
