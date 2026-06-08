"""Move emails to queue-based system

Revision ID: f0af7fedcf50
Revises: 75e9df456e10
Create Date: 2026-05-08 20:19:33.953651

"""


# revision identifiers, used by Alembic.
revision = 'f0af7fedcf50'
down_revision = '75e9df456e10'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


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
    op.add_column('automated_email', sa.Column('policy', sa.Integer(), nullable=True))
    op.create_index(op.f('ix_automated_email_policy'), 'automated_email', ['policy'], unique=False)
    op.drop_column('automated_email', 'currently_sending')
    op.drop_column('automated_email', 'needs_approval')
    op.drop_column('automated_email', 'unapproved_count')
    op.drop_column('automated_email', 'last_send_time')
    op.drop_column('automated_email', 'approved')
    op.drop_column('automated_email', 'revert_changes')
    op.add_column('email', sa.Column('render_data', sa.JSON(), nullable=False, server_default='{}'))
    op.add_column('email', sa.Column('status', sa.Integer(), nullable=False, server_default='172070601'))
    op.add_column('email', sa.Column('generated', sa.DateTime(timezone=True), nullable=False, server_default=sa.text("timezone('utc', current_timestamp)")))
    op.add_column('email', sa.Column('sent', sa.DateTime(timezone=True), nullable=True))
    op.add_column('email', sa.Column('error', sa.Unicode(), nullable=False, server_default=''))
    op.create_index(op.f('ix_email_status'), 'email', ['status'], unique=False)
    op.drop_column('email', 'when')
    op.add_column('automated_email', sa.Column('shared_ident', sa.Unicode(), nullable=False, server_default=''))
    op.add_column('email', sa.Column('shared_ident', sa.Unicode(), nullable=False, server_default=''))
    

def downgrade():
    op.add_column('email', sa.Column('when', postgresql.TIMESTAMP(timezone=True), autoincrement=False, nullable=False, server_default=sa.text("timezone('utc', current_timestamp)")))
    op.drop_index(op.f('ix_email_status'), table_name='email')
    op.drop_column('email', 'error')
    op.drop_column('email', 'sent')
    op.drop_column('email', 'generated')
    op.drop_column('email', 'status')
    op.drop_column('email', 'render_data')
    op.add_column('automated_email', sa.Column('revert_changes', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), autoincrement=False, nullable=False))
    op.add_column('automated_email', sa.Column('approved', sa.BOOLEAN(), server_default=sa.text('false'), autoincrement=False, nullable=False))
    op.add_column('automated_email', sa.Column('last_send_time', postgresql.TIMESTAMP(timezone=True), autoincrement=False, nullable=True))
    op.add_column('automated_email', sa.Column('unapproved_count', sa.INTEGER(), server_default=sa.text('0'), autoincrement=False, nullable=False))
    op.add_column('automated_email', sa.Column('needs_approval', sa.BOOLEAN(), server_default=sa.text('true'), autoincrement=False, nullable=False))
    op.add_column('automated_email', sa.Column('currently_sending', sa.BOOLEAN(), server_default=sa.text('false'), autoincrement=False, nullable=False))
    op.drop_index(op.f('ix_automated_email_policy'), table_name='automated_email')
    op.drop_column('automated_email', 'policy')
    op.drop_column('email', 'shared_ident')
    op.drop_column('automated_email', 'shared_ident')
