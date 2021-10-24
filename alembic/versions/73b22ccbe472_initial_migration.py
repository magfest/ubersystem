"""Initial migration

Revision ID: 73b22ccbe472
Revises: fc791d73e762
Create Date: 2017-04-24 09:08:30.923731

"""


# revision identifiers, used by Alembic.
revision = '73b22ccbe472'
down_revision = 'fc791d73e762'
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


def upgrade():
    op.create_table('attendee_tournament',
    sa.Column('id', residue.UUID(), nullable=False),
    sa.Column('first_name', sa.Unicode(), server_default='', nullable=False),
    sa.Column('last_name', sa.Unicode(), server_default='', nullable=False),
    sa.Column('email', sa.Unicode(), server_default='', nullable=False),
    sa.Column('cellphone', sa.Unicode(), server_default='', nullable=False),
    sa.Column('game', sa.Unicode(), server_default='', nullable=False),
    sa.Column('availability', sa.Unicode(), server_default='', nullable=False),
    sa.Column('format', sa.Unicode(), server_default='', nullable=False),
    sa.Column('experience', sa.Unicode(), server_default='', nullable=False),
    sa.Column('needs', sa.Unicode(), server_default='', nullable=False),
    sa.Column('why', sa.Unicode(), server_default='', nullable=False),
    sa.Column('volunteering', sa.Boolean(), server_default='False', nullable=False),
    sa.Column('status', sa.Integer(), server_default='239694250', nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_attendee_tournament'))
    )


def downgrade():
    op.drop_table('attendee_tournament')
