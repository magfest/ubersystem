"""Refactor guest images for Guidebook

Revision ID: 51daf0d9a514
Revises: 3199020ae71a
Create Date: 2025-05-30 00:54:14.876238

"""


# revision identifiers, used by Alembic.
revision = '51daf0d9a514'
down_revision = '3199020ae71a'
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
    op.create_table('guest_image',
    sa.Column('filename', sa.Unicode(), server_default='', nullable=False),
    sa.Column('content_type', sa.Unicode(), server_default='', nullable=False),
    sa.Column('extension', sa.Unicode(), server_default='', nullable=False),
    sa.Column('is_header', sa.Boolean(), server_default='False', nullable=False),
    sa.Column('is_thumbnail', sa.Boolean(), server_default='False', nullable=False),
    sa.Column('id', residue.UUID(), nullable=False),
    sa.Column('created', residue.UTCDateTime(), server_default=sa.text("timezone('utc', current_timestamp)"), nullable=False),
    sa.Column('last_updated', residue.UTCDateTime(), server_default=sa.text("timezone('utc', current_timestamp)"), nullable=False),
    sa.Column('external_id', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('last_synced', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('guest_id', residue.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['guest_id'], ['guest_group.id'], name=op.f('fk_guest_image_guest_id_guest_group')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_guest_image')),
    )
    op.drop_column('guest_bio', 'pic_filename')
    op.drop_column('guest_bio', 'pic_content_type')


def downgrade():
    op.add_column('guest_bio', sa.Column('pic_content_type', sa.VARCHAR(), server_default=sa.text("''::character varying"), autoincrement=False, nullable=False))
    op.add_column('guest_bio', sa.Column('pic_filename', sa.VARCHAR(), server_default=sa.text("''::character varying"), autoincrement=False, nullable=False))
    op.drop_table('guest_image')
