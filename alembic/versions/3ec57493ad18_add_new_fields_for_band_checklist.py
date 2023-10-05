"""Add new fields for band checklist

Revision ID: 3ec57493ad18
Revises: ceb6dd682832
Create Date: 2023-10-05 01:00:24.836124

"""


# revision identifiers, used by Alembic.
revision = '3ec57493ad18'
down_revision = 'ceb6dd682832'
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
    with op.batch_alter_table("guest_autograph") as batch_op:
        batch_op.add_column(sa.Column('rock_island_autographs', sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column('rock_island_length', sa.Integer(), server_default='60', nullable=False))
    
    with op.batch_alter_table("guest_bio") as batch_op:
        batch_op.add_column(sa.Column('spotify', sa.Unicode(), server_default='', nullable=False))

    with op.batch_alter_table("guest_stage_plot") as batch_op:
        batch_op.add_column(sa.Column('notes', sa.Unicode(), server_default='', nullable=False))


def downgrade():
    op.drop_column('guest_stage_plot', 'notes')
    op.drop_column('guest_bio', 'spotify')
    op.drop_column('guest_autograph', 'rock_island_length')
    op.drop_column('guest_autograph', 'rock_island_autographs')
