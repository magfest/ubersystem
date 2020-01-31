"""Add Art Show Piece table

Revision ID: f812bc84e064
Revises: e1d3c11eb9dd
Create Date: 2018-08-21 04:16:15.761913

"""


# revision identifiers, used by Alembic.
revision = 'f812bc84e064'
down_revision = 'e1d3c11eb9dd'
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
    op.create_table('art_show_piece',
    sa.Column('id', residue.UUID(), nullable=False),
    sa.Column('app_id', residue.UUID(), nullable=True),
    sa.Column('piece_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.Unicode(), server_default='', nullable=False),
    sa.Column('for_sale', sa.Boolean(), server_default='False', nullable=False),
    sa.Column('type', sa.Integer(), server_default='36230926', nullable=False),
    sa.Column('gallery', sa.Integer(), server_default='187837110', nullable=False),
    sa.Column('media', sa.Unicode(), server_default='', nullable=False),
    sa.Column('print_run_num', sa.Integer(), server_default='0', nullable=True),
    sa.Column('print_run_total', sa.Integer(), server_default='0', nullable=True),
    sa.Column('opening_bid', sa.Integer(), server_default='0', nullable=True),
    sa.Column('quick_sale_price', sa.Integer(), server_default='0', nullable=True),
    sa.Column('no_quick_sale', sa.Boolean(), server_default='False', nullable=False),
    sa.Column('status', sa.Integer(), server_default='34456864', nullable=False),
    sa.ForeignKeyConstraint(['app_id'], ['art_show_application.id'], name=op.f('fk_art_show_pieces_app_id_art_show_application'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_art_show_pieces'))
    )


def downgrade():
    op.drop_table('art_show_piece')
