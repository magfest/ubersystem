"""Add StripeTransaction table

Revision ID: 3723d12f8740
Revises: 691be8fa880d
Create Date: 2017-05-05 02:47:59.225336

"""


# revision identifiers, used by Alembic.
revision = '3723d12f8740'
down_revision = '691be8fa880d'
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


def upgrade():
    op.create_table('stripe_transaction',
    sa.Column('id', residue.UUID(), nullable=False),
    sa.Column('stripe_id', sa.Unicode(), server_default='', nullable=True),
    sa.Column('type', sa.Integer(), server_default='186441959', nullable=False),
    sa.Column('amount', sa.Integer(), nullable=False),
    sa.Column('when', residue.UTCDateTime(), nullable=False),
    sa.Column('who', sa.Unicode(), server_default='', nullable=False),
    sa.Column('desc', sa.Unicode(), server_default='', nullable=False),
    sa.Column('fk_id', residue.UUID(), nullable=False),
    sa.Column('fk_model', sa.Unicode(), server_default='', nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_stripe_transaction'))
    )


def downgrade():
    op.drop_table('stripe_transaction')
