"""Added document uploads and team deletion

Revision ID: 735063d71b57
Revises: 76e2905cff66
Create Date: 2017-11-26 00:16:52.930412
"""

# revision identifiers, used by Alembic.
revision = '735063d71b57'
down_revision = '76e2905cff66'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa
import residue

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


def upgrade():
    op.create_table('mits_document',
    sa.Column('id', residue.UUID(), nullable=False),
    sa.Column('team_id', residue.UUID(), nullable=False),
    sa.Column('filename', sa.Unicode(), server_default='', nullable=False),
    sa.Column('description', sa.Unicode(), server_default='', nullable=False),
    sa.ForeignKeyConstraint(['team_id'], ['mits_team.id'], name=op.f('fk_mits_document_team_id_mits_team')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_mits_document'))
    )

    if is_sqlite:
        with op.batch_alter_table('mits_team', reflect_kwargs=sqlite_reflect_kwargs) as batch_op:
            batch_op.add_column(sa.Column('deleted', sa.Boolean(), server_default='False', nullable=False))
            batch_op.add_column(sa.Column('duplicate_of', residue.UUID(), nullable=True))
    else:
        op.add_column('mits_team', sa.Column('deleted', sa.Boolean(), server_default='False', nullable=False))
        op.add_column('mits_team', sa.Column('duplicate_of', residue.UUID(), nullable=True))


def downgrade():
    op.drop_column('mits_team', 'duplicate_of')
    op.drop_column('mits_team', 'deleted')
    op.drop_table('mits_document')
