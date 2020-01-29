"""Add bidder signup

Revision ID: 54227ab70c17
Revises: 14ef3a47a1d6
Create Date: 2018-10-15 17:02:07.266972

"""


# revision identifiers, used by Alembic.
revision = '54227ab70c17'
down_revision = '14ef3a47a1d6'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa
import residue


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
    op.create_table('art_show_bidder',
    sa.Column('id', residue.UUID(), nullable=False),
    sa.Column('attendee_id', residue.UUID(), nullable=True),
    sa.Column('bidder_num', sa.Unicode(), server_default='', nullable=False),
    sa.Column('hotel_name', sa.Unicode(), server_default='', nullable=False),
    sa.Column('hotel_room_num', sa.Unicode(), server_default='', nullable=False),
    sa.Column('admin_notes', sa.Unicode(), server_default='', nullable=False),
    sa.Column('signed_up', residue.UTCDateTime(), nullable=True),
    sa.ForeignKeyConstraint(['attendee_id'], ['attendee.id'], name=op.f('fk_art_show_bidder_attendee_id_attendee'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_art_show_bidder'))
    )


def downgrade():
    op.drop_table('art_show_bidder')
