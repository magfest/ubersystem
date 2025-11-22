"""Add art show assignments map

Revision ID: cfdb41ec82b8
Revises: 4cf28df7a212
Create Date: 2025-11-20 01:57:28.817425

"""


# revision identifiers, used by Alembic.
revision = 'cfdb41ec82b8'
down_revision = '4cf28df7a212'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
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
    op.create_table('art_show_panel',
    sa.Column('id', residue.UUID(), nullable=False),
    sa.Column('created', residue.UTCDateTime(), server_default=sa.text("timezone('utc', current_timestamp)"), nullable=False),
    sa.Column('last_updated', residue.UTCDateTime(), server_default=sa.text("timezone('utc', current_timestamp)"), nullable=False),
    sa.Column('external_id', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('last_synced', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('gallery', sa.Integer(), server_default='187837110', nullable=False),
    sa.Column('origin_x', sa.Integer(), server_default='0', nullable=False),
    sa.Column('origin_y', sa.Integer(), server_default='0', nullable=False),
    sa.Column('terminus_x', sa.Integer(), server_default='0', nullable=False),
    sa.Column('terminus_y', sa.Integer(), server_default='0', nullable=False),
    sa.Column('assignable_sides', sa.Integer(), server_default='31539058', nullable=False),
    sa.Column('start_label', sa.Unicode(), server_default='', nullable=False),
    sa.Column('end_label', sa.Unicode(), server_default='', nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_art_show_panel'))
    )
    op.create_table('art_panel_assignment',
    sa.Column('id', residue.UUID(), nullable=False),
    sa.Column('created', residue.UTCDateTime(), server_default=sa.text("timezone('utc', current_timestamp)"), nullable=False),
    sa.Column('last_updated', residue.UTCDateTime(), server_default=sa.text("timezone('utc', current_timestamp)"), nullable=False),
    sa.Column('external_id', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('last_synced', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('panel_id', residue.UUID(), nullable=False),
    sa.Column('app_id', residue.UUID(), nullable=False),
    sa.Column('manual', sa.Boolean(), server_default='False', nullable=False),
    sa.Column('assigned_side', sa.Integer(), server_default='184531092', nullable=False),
    sa.ForeignKeyConstraint(['app_id'], ['art_show_application.id'], name=op.f('fk_art_panel_assignment_app_id_art_show_application')),
    sa.ForeignKeyConstraint(['panel_id'], ['art_show_panel.id'], name=op.f('fk_art_panel_assignment_panel_id_art_show_panel')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_art_panel_assignment'))
    )
    op.create_index('ix_art_panel_assignment_assigned_side', 'art_panel_assignment', ['assigned_side'], unique=False)
    op.create_index('ix_art_panel_assignment_panel_id', 'art_panel_assignment', ['panel_id'], unique=False)
    op.create_unique_constraint(op.f('uq_art_panel_assignment_panel_id'), 'art_panel_assignment', ['panel_id', 'assigned_side'])
    op.create_unique_constraint(op.f('uq_art_show_panel_gallery'), 'art_show_panel', ['gallery', 'origin_x', 'origin_y', 'terminus_x', 'terminus_y'])


def downgrade():
    op.drop_constraint(op.f('uq_art_show_panel_origin_x'), 'art_show_panel', type_='unique')
    op.drop_constraint(op.f('uq_art_panel_assignment_panel_id'), 'art_panel_assignment', type_='unique')
    op.drop_index('ix_art_panel_assignment_panel_id', table_name='art_panel_assignment')
    op.drop_index('ix_art_panel_assignment_assigned_side', table_name='art_panel_assignment')
    op.drop_table('art_panel_assignment')
    op.drop_table('art_show_panel')
