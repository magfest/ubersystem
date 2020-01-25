"""Add Promo Code Groups to prereg

Revision ID: 523e3d243395
Revises: d1ae7f4f7767
Create Date: 2019-03-05 03:43:43.048891

"""


# revision identifiers, used by Alembic.
revision = '523e3d243395'
down_revision = 'd1ae7f4f7767'
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
    op.create_table('promo_code_group',
    sa.Column('id', residue.UUID(), nullable=False),
    sa.Column('name', sa.Unicode(), server_default='', nullable=False),
    sa.Column('code', sa.Unicode(), server_default='', nullable=False),
    sa.Column('buyer_id', residue.UUID(), nullable=True),
    sa.ForeignKeyConstraint(['buyer_id'], ['attendee.id'], name=op.f('fk_promo_code_group_buyer_id_attendee'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_promo_code_group'))
    )
    op.add_column('promo_code', sa.Column('group_id', residue.UUID(), nullable=True))
    op.create_foreign_key(op.f('fk_promo_code_group_id_promo_code_group'), 'promo_code', 'promo_code_group', ['group_id'], ['id'], ondelete='SET NULL')


def downgrade():
    op.drop_constraint(op.f('fk_promo_code_group_id_promo_code_group'), 'promo_code', type_='foreignkey')
    op.drop_column('promo_code', 'group_id')
    op.drop_table('promo_code_group')
