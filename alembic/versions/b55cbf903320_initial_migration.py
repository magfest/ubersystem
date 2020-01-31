"""Initial migration

Revision ID: b55cbf903320
Revises: af64b33e950a
Create Date: 2018-05-08 23:18:35.150928

"""


# revision identifiers, used by Alembic.
revision = 'b55cbf903320'
down_revision = 'af64b33e950a'
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
    op.create_table('art_show_application',
    sa.Column('id', residue.UUID(), nullable=False),
    sa.Column('attendee_id', residue.UUID(), nullable=True),
    sa.Column('artist_name', residue.CoerceUTF8(), nullable=False),
    sa.Column('panels', sa.Integer(), server_default='0', nullable=False),
    sa.Column('tables', sa.Integer(), server_default='0', nullable=False),
    sa.Column('description', residue.CoerceUTF8(), nullable=False),
    sa.Column('website', residue.CoerceUTF8(), nullable=False),
    sa.Column('special_needs', residue.CoerceUTF8(), nullable=False),
    sa.Column('status', sa.Integer(), server_default='172070601', nullable=False),
    sa.Column('admin_notes', residue.CoerceUTF8(), nullable=False),
    sa.Column('base_price', sa.Integer(), server_default='0', nullable=False),
    sa.Column('overridden_price', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['attendee_id'], ['attendee.id'], name=op.f('fk_art_show_application_attendee_id_attendee'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_art_show_application'))
    )


def downgrade():
    op.drop_table('art_show_application')

