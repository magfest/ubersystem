"""Add indie arcade applications

Revision ID: 57be7838a54f
Revises: b561dae06c39
Create Date: 2025-07-02 14:43:38.103468

"""


# revision identifiers, used by Alembic.
revision = '57be7838a54f'
down_revision = 'b561dae06c39'
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
    op.add_column('indie_game', sa.Column('primary_contact_id', sa.Uuid(as_uuid=False), nullable=True))
    op.add_column('indie_game', sa.Column('game_hours', sa.Unicode(), server_default='', nullable=False))
    op.add_column('indie_game', sa.Column('game_hours_text', sa.Unicode(), server_default='', nullable=False))
    op.add_column('indie_game', sa.Column('game_end_time', sa.Boolean(), server_default='False', nullable=False))
    op.add_column('indie_game', sa.Column('floorspace', sa.Integer(), nullable=True))
    op.add_column('indie_game', sa.Column('floorspace_text', sa.Unicode(), server_default='', nullable=False))
    op.add_column('indie_game', sa.Column('cabinet_type', sa.Integer(), nullable=True))
    op.add_column('indie_game', sa.Column('cabinet_type_text', sa.Unicode(), server_default='', nullable=False))
    op.add_column('indie_game', sa.Column('sanitation_requests', sa.Unicode(), server_default='', nullable=False))
    op.add_column('indie_game', sa.Column('transit_needs', sa.Unicode(), server_default='', nullable=False))
    op.add_column('indie_game', sa.Column('found_how', sa.Unicode(), server_default='', nullable=False))
    op.add_column('indie_game', sa.Column('read_faq', sa.Unicode(), server_default='', nullable=False))
    op.add_column('indie_game', sa.Column('mailing_list', sa.Boolean(), server_default='False', nullable=False))
    op.add_column('indie_game', sa.Column('agreed_equipment', sa.Boolean(), server_default='False', nullable=False))
    op.create_foreign_key(op.f('fk_indie_game_primary_contact_id_indie_developer'), 'indie_game', 'indie_developer', ['primary_contact_id'], ['id'], ondelete='SET NULL')


def downgrade():
    op.drop_constraint(op.f('fk_indie_game_primary_contact_id_indie_developer'), 'indie_game', type_='foreignkey')
    op.drop_column('indie_game', 'agreed_equipment')
    op.drop_column('indie_game', 'mailing_list')
    op.drop_column('indie_game', 'read_faq')
    op.drop_column('indie_game', 'found_how')
    op.drop_column('indie_game', 'transit_needs')
    op.drop_column('indie_game', 'sanitation_requests')
    op.drop_column('indie_game', 'cabinet_type_text')
    op.drop_column('indie_game', 'cabinet_type')
    op.drop_column('indie_game', 'floorspace_text')
    op.drop_column('indie_game', 'floorspace')
    op.drop_column('indie_game', 'game_end_time')
    op.drop_column('indie_game', 'game_hours_text')
    op.drop_column('indie_game', 'game_hours')
    op.drop_column('indie_game', 'primary_contact_id')
