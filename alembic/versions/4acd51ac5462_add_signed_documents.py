"""Add signed documents

Revision ID: 4acd51ac5462
Revises: ed2acba6f8bd
Create Date: 2022-06-28 03:19:40.614556

"""


# revision identifiers, used by Alembic.
revision = '4acd51ac5462'
down_revision = 'ed2acba6f8bd'
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
    op.create_table('signed_document',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('fk_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('model', sa.Unicode(), server_default='', nullable=False),
    sa.Column('document_id', sa.Unicode(), server_default='', nullable=False),
    sa.Column('link', sa.Unicode(), server_default='', nullable=False),
    sa.Column('ident', sa.Unicode(), server_default='', nullable=False),
    sa.Column('signed', sa.DateTime(timezone=True), server_default=None),
    sa.Column('declined', sa.DateTime(timezone=True), server_default=None),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_signed_document'))
    )
    op.create_index(op.f('ix_signed_document_fk_id'), 'signed_document', ['fk_id'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_signed_document_fk_id'), table_name='signed_document')
    op.drop_table('signed_document')
