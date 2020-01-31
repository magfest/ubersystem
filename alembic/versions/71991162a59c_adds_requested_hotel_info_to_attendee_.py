"""Adds requested_hotel_info to attendee table

Revision ID: 71991162a59c
Revises: edd7b60ea4b4
Create Date: 2017-07-10 14:35:20.810300

"""


# revision identifiers, used by Alembic.
revision = '71991162a59c'
down_revision = 'edd7b60ea4b4'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa



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
    if is_sqlite:
        def listen_for_reflect(inspector, table, column_info):
            """Adds parenthesis around SQLite datetime defaults for utcnow."""
            if column_info['default'] == "datetime('now', 'utc')":
                column_info['default'] = utcnow_server_default

        with op.batch_alter_table(
                'attendee',
                reflect_kwargs=dict(listeners=[('column_reflect', listen_for_reflect)])) as batch_op:
            batch_op.add_column(sa.Column('requested_hotel_info', sa.Boolean(), server_default='False', nullable=False))
    else:
        op.add_column('attendee', sa.Column('requested_hotel_info', sa.Boolean(), server_default='False', nullable=False))


def downgrade():
    op.drop_column('attendee', 'requested_hotel_info')
