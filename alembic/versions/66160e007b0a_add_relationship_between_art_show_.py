"""Add relationship between art show bidders and pieces

Revision ID: 66160e007b0a
Revises: 29acada458c8
Create Date: 2023-11-22 02:12:44.571570

"""


# revision identifiers, used by Alembic.
revision = '66160e007b0a'
down_revision = '29acada458c8'
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
    op.add_column('art_show_piece', sa.Column('winning_bidder_id', residue.UUID(), nullable=True))
    op.create_foreign_key(op.f('fk_art_show_piece_winning_bidder_id_art_show_bidder'), 'art_show_piece', 'art_show_bidder', ['winning_bidder_id'], ['id'], ondelete='SET NULL')


def downgrade():
    op.drop_constraint(op.f('fk_art_show_piece_winning_bidder_id_art_show_bidder'), 'art_show_piece', type_='foreignkey')
    op.drop_column('art_show_piece', 'winning_bidder_id')
