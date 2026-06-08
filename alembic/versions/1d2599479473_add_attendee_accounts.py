"""Add attendee accounts

Revision ID: 1d2599479473
Revises: af733a3c421c
Create Date: 2021-08-28 23:21:40.807636

"""


# revision identifiers, used by Alembic.
revision = '1d2599479473'
down_revision = 'af733a3c421c'
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
    op.create_table('attendee_account',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('email', sa.Unicode(), server_default='', nullable=False),
    sa.Column('hashed', sa.Unicode(), server_default='', nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_attendee_account'))
    )
    op.create_table('attendee_attendee_account',
    sa.Column('attendee_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('attendee_account_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.ForeignKeyConstraint(['attendee_account_id'], ['attendee_account.id'], name=op.f('fk_attendee_attendee_account_attendee_account_id_attendee_account')),
    sa.ForeignKeyConstraint(['attendee_id'], ['attendee.id'], name=op.f('fk_attendee_attendee_account_attendee_id_attendee')),
    sa.UniqueConstraint('attendee_id', 'attendee_account_id', name=op.f('uq_attendee_attendee_account_attendee_id'))
    )
    op.create_index('ix_attendee_attendee_account_attendee_account_id', 'attendee_attendee_account', ['attendee_account_id'], unique=False)
    op.create_index('ix_attendee_attendee_account_attendee_id', 'attendee_attendee_account', ['attendee_id'], unique=False)
    op.alter_column('mits_team', 'concurrent_attendees',
               existing_type=sa.INTEGER(),
               nullable=False)


def downgrade():
    op.alter_column('mits_team', 'concurrent_attendees',
               existing_type=sa.INTEGER(),
               nullable=True)
    op.drop_index('ix_attendee_attendee_account_attendee_id', table_name='attendee_attendee_account')
    op.drop_index('ix_attendee_attendee_account_attendee_account_id', table_name='attendee_attendee_account')
    op.drop_table('attendee_attendee_account')
    op.drop_table('attendee_account')
