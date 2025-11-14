"""Move event locations to DB

Revision ID: 417aacb2c6e9
Revises: b1869cea73b5
Create Date: 2025-11-10 07:46:54.359119

"""


# revision identifiers, used by Alembic.
revision = '417aacb2c6e9'
down_revision = 'b1869cea73b5'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
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
    op.create_table('event_location',
    sa.Column('id', residue.UUID(), nullable=False),
    sa.Column('created', residue.UTCDateTime(), server_default=sa.text("timezone('utc', current_timestamp)"), nullable=False),
    sa.Column('last_updated', residue.UTCDateTime(), server_default=sa.text("timezone('utc', current_timestamp)"), nullable=False),
    sa.Column('external_id', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('last_synced', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('department_id', residue.UUID(), nullable=True),
    sa.Column('category', sa.Integer(), nullable=True),
    sa.Column('name', sa.Unicode(), server_default='', nullable=False),
    sa.Column('room', sa.Unicode(), server_default='', nullable=False),
    sa.Column('tracks', sa.Unicode(), server_default='', nullable=False),
    sa.ForeignKeyConstraint(['department_id'], ['department.id'], name=op.f('fk_event_location_department_id_department'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_event_location'))
    )
    op.add_column('event', sa.Column('event_location_id', residue.UUID(), nullable=True))
    op.add_column('event', sa.Column('category', sa.Integer(), nullable=True))
    op.add_column('event', sa.Column('department_id', residue.UUID(), nullable=True))
    op.add_column('event', sa.Column('tracks', sa.Unicode(), server_default='', nullable=False))
    op.create_foreign_key(op.f('fk_event_department_id_department'), 'event', 'department', ['department_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key(op.f('fk_event_location_id_event_location'), 'event', 'event_location', ['event_location_id'], ['id'], ondelete='SET NULL')
    op.drop_column('event', 'location')
    op.drop_column('event', 'track')
    op.drop_column('panel_application', 'track')


def downgrade():
    op.add_column('event', sa.Column('location', sa.INTEGER(), autoincrement=False, nullable=True))
    op.add_column('panel_application', sa.Column('track', sa.VARCHAR(), server_default=sa.text("''::character varying"), autoincrement=False, nullable=False))
    op.add_column('event', sa.Column('track', sa.VARCHAR(), server_default=sa.text("''::character varying"), autoincrement=False, nullable=False))
    op.drop_constraint(op.f('fk_event_department_id_department'), 'event', type_='foreignkey')
    op.drop_constraint(op.f('fk_event_location_id_event_location'), 'event', type_='foreignkey')
    op.drop_column('event', 'tracks')
    op.drop_column('event', 'department_id')
    op.drop_column('event', 'category')
    op.drop_column('event', 'event_location_id')
    op.drop_table('event_location')
