"""Add MITS Panel Application table.

Revision ID: 72f97bdad2fa
Revises: b574c0577253
Create Date: 2018-10-04 23:14:03.153533

"""


# revision identifiers, used by Alembic.
revision = '72f97bdad2fa'
down_revision = 'b574c0577253'
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
    op.create_table('mits_panel_application',
    sa.Column('id', residue.UUID(), nullable=False),
    sa.Column('team_id', residue.UUID(), nullable=False),
    sa.Column('name', sa.Unicode(), server_default='', nullable=False),
    sa.Column('description', sa.Unicode(), server_default='', nullable=False),
    sa.Column('length', sa.Integer(), server_default='212285177', nullable=False),
    sa.Column('participation_interest', sa.Boolean(), server_default='False', nullable=False),
    sa.ForeignKeyConstraint(['team_id'], ['mits_team.id'], name=op.f('fk_mits_panel_application_team_id_mits_team')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_mits_panel_application'))
    )
    op.add_column('mits_team', sa.Column('showcase_interest', sa.Boolean(), nullable=True))
    op.alter_column('mits_team', 'panel_interest', server_default=None, nullable=True)


def downgrade():
    op.drop_table('mits_panel_application')
    op.drop_column('mits_team', 'showcase_interest')
    op.alter_column('mits_team', 'panel_interest', server_default=False, nullable=False)
