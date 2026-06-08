"""Add autograph, interview, and travel plan checklist items

Revision ID: a1a5bd54b2aa
Revises: f619fbd56912
Create Date: 2017-09-21 07:17:46.817443

"""


# revision identifiers, used by Alembic.
revision = 'a1a5bd54b2aa'
down_revision = 'f619fbd56912'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


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


def upgrade():
    op.create_table('guest_autograph',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('guest_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('num', sa.Integer(), server_default='0', nullable=False),
    sa.Column('length', sa.Integer(), server_default='60', nullable=False),
    sa.ForeignKeyConstraint(['guest_id'], ['guest_group.id'], name=op.f('fk_guest_autograph_guest_id_guest_group')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_guest_autograph')),
    sa.UniqueConstraint('guest_id', name=op.f('uq_guest_autograph_guest_id'))
    )
    op.create_table('guest_interview',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('guest_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('will_interview', sa.Boolean(), server_default='False', nullable=False),
    sa.Column('email', sa.Unicode(), server_default='', nullable=False),
    sa.Column('direct_contact', sa.Boolean(), server_default='False', nullable=False),
    sa.ForeignKeyConstraint(['guest_id'], ['guest_group.id'], name=op.f('fk_guest_interview_guest_id_guest_group')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_guest_interview')),
    sa.UniqueConstraint('guest_id', name=op.f('uq_guest_interview_guest_id'))
    )
    op.create_table('guest_travel_plans',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('guest_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('modes', sa.Unicode(), server_default='', nullable=False),
    sa.Column('modes_text', sa.Unicode(), server_default='', nullable=False),
    sa.Column('details', sa.Unicode(), server_default='', nullable=False),
    sa.ForeignKeyConstraint(['guest_id'], ['guest_group.id'], name=op.f('fk_guest_travel_plans_guest_id_guest_group')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_guest_travel_plans')),
    sa.UniqueConstraint('guest_id', name=op.f('uq_guest_travel_plans_guest_id'))
    )


def downgrade():
    op.drop_table('guest_travel_plans')
    op.drop_table('guest_interview')
    op.drop_table('guest_autograph')

