"""Add Marketplace applications

Revision ID: 9e721eb0b45c
Revises: fa869546b8ca
Create Date: 2019-08-25 00:13:12.508824

"""


# revision identifiers, used by Alembic.
revision = '9e721eb0b45c'
down_revision = 'fa869546b8ca'
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
    op.create_table('marketplace_application',
    sa.Column('id', residue.UUID(), nullable=False),
    sa.Column('attendee_id', residue.UUID(), nullable=True),
    sa.Column('business_name', sa.Unicode(), server_default='', nullable=False),
    sa.Column('status', sa.Integer(), server_default='172070601', nullable=False),
    sa.Column('registered', residue.UTCDateTime(), server_default=sa.text("timezone('utc', current_timestamp)"), nullable=False),
    sa.Column('approved', residue.UTCDateTime(), nullable=True),
    sa.Column('categories', sa.Unicode(), server_default='', nullable=False),
    sa.Column('categories_text', sa.Unicode(), server_default='', nullable=False),
    sa.Column('description', sa.Unicode(), server_default='', nullable=False),
    sa.Column('special_needs', sa.Unicode(), server_default='', nullable=False),
    sa.Column('admin_notes', sa.Unicode(), server_default='', nullable=False),
    sa.Column('base_price', sa.Integer(), server_default='0', nullable=False),
    sa.Column('overridden_price', sa.Integer(), nullable=True),
    sa.Column('amount_paid', sa.Integer(), server_default='0', nullable=False),
    sa.ForeignKeyConstraint(['attendee_id'], ['attendee.id'], name=op.f('fk_marketplace_application_attendee_id_attendee'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_marketplace_application'))
    )
    op.create_index(op.f('ix_marketplace_application_amount_paid'), 'marketplace_application', ['amount_paid'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_marketplace_application_amount_paid'), table_name='marketplace_application')
    op.drop_table('marketplace_application')
