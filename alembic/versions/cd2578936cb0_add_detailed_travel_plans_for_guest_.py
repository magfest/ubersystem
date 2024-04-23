"""Add detailed travel plans for guest checklist

Revision ID: cd2578936cb0
Revises: 28bf25495d40
Create Date: 2022-11-13 06:10:13.224264

"""


# revision identifiers, used by Alembic.
revision = 'cd2578936cb0'
down_revision = '28bf25495d40'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa
from sqlalchemy.types import UUID


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
    op.create_table('guest_detailed_travel_plan',
    sa.Column('id', UUID(), nullable=False),
    sa.Column('travel_plans_id', UUID(), nullable=True),
    sa.Column('mode', sa.Integer(), nullable=False),
    sa.Column('mode_text', sa.Unicode(), server_default='', nullable=False),
    sa.Column('traveller', sa.Unicode(), server_default='', nullable=False),
    sa.Column('companions', sa.Unicode(), server_default='', nullable=False),
    sa.Column('luggage_needs', sa.Unicode(), server_default='', nullable=False),
    sa.Column('contact_email', sa.Unicode(), server_default='', nullable=False),
    sa.Column('contact_phone', sa.Unicode(), server_default='', nullable=False),
    sa.Column('arrival_time', DateTime(), nullable=False),
    sa.Column('arrival_details', sa.Unicode(), server_default='', nullable=False),
    sa.Column('departure_time', DateTime(), nullable=False),
    sa.Column('departure_details', sa.Unicode(), server_default='', nullable=False),
    sa.Column('extra_details', sa.Unicode(), server_default='', nullable=False),
    sa.ForeignKeyConstraint(['travel_plans_id'], ['guest_travel_plans.id'], name=op.f('fk_guest_detailed_travel_plan_travel_plans_id_guest_travel_plans')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_guest_detailed_travel_plan'))
    )


def downgrade():
    op.drop_table('guest_detailed_travel_plan')
