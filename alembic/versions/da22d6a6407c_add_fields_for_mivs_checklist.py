"""Add fields for MIVS checklist

Revision ID: da22d6a6407c
Revises: bf427bc2a7f2
Create Date: 2018-11-20 17:36:05.248730

"""


# revision identifiers, used by Alembic.
revision = 'da22d6a6407c'
down_revision = 'bf427bc2a7f2'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa



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
    op.add_column('indie_studio', sa.Column('accepted_core_hours', sa.Boolean(), server_default='False', nullable=False))
    op.add_column('indie_studio', sa.Column('completed_discussion', sa.Boolean(), server_default='False', nullable=False))
    op.add_column('indie_studio', sa.Column('discussion_emails', sa.Unicode(), server_default='', nullable=False))
    op.add_column('indie_studio', sa.Column('email_for_hotel', sa.Unicode(), server_default='', nullable=False))
    op.add_column('indie_studio', sa.Column('name_for_hotel', sa.Unicode(), server_default='', nullable=False))
    op.add_column('indie_studio', sa.Column('needs_hotel_space', sa.Boolean(), nullable=True))
    op.add_column('indie_studio', sa.Column('read_handbook', sa.Boolean(), server_default='False', nullable=False))
    op.add_column('indie_studio', sa.Column('selling_at_event', sa.Boolean(), nullable=True))
    op.add_column('indie_studio', sa.Column('training_password', sa.Unicode(), server_default='', nullable=False))


def downgrade():
    op.drop_column('indie_studio', 'training_password')
    op.drop_column('indie_studio', 'selling_at_event')
    op.drop_column('indie_studio', 'read_handbook')
    op.drop_column('indie_studio', 'needs_hotel_space')
    op.drop_column('indie_studio', 'name_for_hotel')
    op.drop_column('indie_studio', 'email_for_hotel')
    op.drop_column('indie_studio', 'discussion_emails')
    op.drop_column('indie_studio', 'completed_discussion')
    op.drop_column('indie_studio', 'accepted_core_hours')
