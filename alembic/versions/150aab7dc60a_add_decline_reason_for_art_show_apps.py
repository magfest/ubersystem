"""Add decline_reason for art show apps

Revision ID: 150aab7dc60a
Revises: 34f9d87b62f4
Create Date: 2025-07-10 07:05:05.803045

"""


# revision identifiers, used by Alembic.
revision = '150aab7dc60a'
down_revision = '34f9d87b62f4'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa



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
    op.drop_constraint('uq_art_show_agent_code_attendee_id', 'art_show_agent_code', type_='unique')
    op.add_column('art_show_application', sa.Column('decline_reason', sa.Unicode(), server_default='', nullable=False))
    op.drop_column('art_show_application', 'hotel_room_num')
    op.drop_column('art_show_application', 'hotel_name')
    op.drop_column('art_show_bidder', 'hotel_room_num')
    op.drop_column('art_show_bidder', 'hotel_name')


def downgrade():
    op.create_unique_constraint('uq_art_show_agent_code_attendee_id', 'art_show_agent_code', ['attendee_id'])
    op.add_column('art_show_application', sa.Column('hotel_name', sa.VARCHAR(), server_default=sa.text("''::character varying"), autoincrement=False, nullable=False))
    op.add_column('art_show_application', sa.Column('hotel_room_num', sa.VARCHAR(), server_default=sa.text("''::character varying"), autoincrement=False, nullable=False))
    op.add_column('art_show_bidder', sa.Column('hotel_name', sa.VARCHAR(), server_default=sa.text("''::character varying"), autoincrement=False, nullable=False))
    op.add_column('art_show_bidder', sa.Column('hotel_room_num', sa.VARCHAR(), server_default=sa.text("''::character varying"), autoincrement=False, nullable=False))
    op.drop_column('art_show_application', 'decline_reason')
