"""Update artist marketplace application

Revision ID: 318d761a5c62
Revises: 99596530b8e4
Create Date: 2024-10-02 20:54:47.659096

"""


# revision identifiers, used by Alembic.
revision = '318d761a5c62'
down_revision = '99596530b8e4'
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
    op.create_table('artist_marketplace_application',
    sa.Column('id', residue.UUID(), nullable=False),
    sa.Column('created', residue.UTCDateTime(), server_default=sa.text("timezone('utc', current_timestamp)"), nullable=False),
    sa.Column('last_updated', residue.UTCDateTime(), server_default=sa.text("timezone('utc', current_timestamp)"), nullable=False),
    sa.Column('external_id', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('last_synced', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('attendee_id', residue.UUID(), nullable=False),
    sa.Column('name', sa.Unicode(), server_default='', nullable=False),
    sa.Column('display_name', sa.Unicode(), server_default='', nullable=False),
    sa.Column('email_address', sa.Unicode(), server_default='', nullable=False),
    sa.Column('website', sa.Unicode(), server_default='', nullable=False),
    sa.Column('tax_number', sa.Unicode(), server_default='', nullable=False),
    sa.Column('seating_requests', sa.Unicode(), server_default='', nullable=False),
    sa.Column('accessibility_requests', sa.Unicode(), server_default='', nullable=False),
    sa.Column('terms_accepted', sa.Boolean(), server_default='False', nullable=False),
    sa.Column('status', sa.Integer(), server_default='196944751', nullable=False),
    sa.Column('registered', residue.UTCDateTime(), server_default=sa.text("timezone('utc', current_timestamp)"), nullable=False),
    sa.Column('accepted', residue.UTCDateTime(), nullable=True),
    sa.Column('admin_notes', sa.Unicode(), server_default='', nullable=False),
    sa.Column('overridden_price', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['attendee_id'], ['attendee.id'], name=op.f('fk_artist_marketplace_application_attendee_id_attendee')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_artist_marketplace_application'))
    )
    op.drop_table('marketplace_application')
    op.add_column('receipt_item', sa.Column('fk_id', residue.UUID(), nullable=True))
    op.add_column('receipt_item', sa.Column('fk_model', sa.Unicode(), server_default='', nullable=False))


def downgrade():
    op.drop_column('receipt_item', 'fk_model')
    op.drop_column('receipt_item', 'fk_id')
    op.create_table('marketplace_application',
    sa.Column('id', postgresql.UUID(), autoincrement=False, nullable=False),
    sa.Column('attendee_id', postgresql.UUID(), autoincrement=False, nullable=True),
    sa.Column('business_name', sa.VARCHAR(), server_default=sa.text("''::character varying"), autoincrement=False, nullable=False),
    sa.Column('status', sa.INTEGER(), server_default=sa.text('172070601'), autoincrement=False, nullable=False),
    sa.Column('registered', postgresql.TIMESTAMP(), server_default=sa.text("timezone('utc'::text, CURRENT_TIMESTAMP)"), autoincrement=False, nullable=False),
    sa.Column('approved', postgresql.TIMESTAMP(), autoincrement=False, nullable=True),
    sa.Column('categories', sa.VARCHAR(), server_default=sa.text("''::character varying"), autoincrement=False, nullable=False),
    sa.Column('categories_text', sa.VARCHAR(), server_default=sa.text("''::character varying"), autoincrement=False, nullable=False),
    sa.Column('description', sa.VARCHAR(), server_default=sa.text("''::character varying"), autoincrement=False, nullable=False),
    sa.Column('special_needs', sa.VARCHAR(), server_default=sa.text("''::character varying"), autoincrement=False, nullable=False),
    sa.Column('admin_notes', sa.VARCHAR(), server_default=sa.text("''::character varying"), autoincrement=False, nullable=False),
    sa.Column('overridden_price', sa.INTEGER(), autoincrement=False, nullable=True),
    sa.Column('created', postgresql.TIMESTAMP(), server_default=sa.text("timezone('utc'::text, CURRENT_TIMESTAMP)"), autoincrement=False, nullable=False),
    sa.Column('last_updated', postgresql.TIMESTAMP(), server_default=sa.text("timezone('utc'::text, CURRENT_TIMESTAMP)"), autoincrement=False, nullable=False),
    sa.Column('external_id', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), autoincrement=False, nullable=False),
    sa.Column('last_synced', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), autoincrement=False, nullable=False),
    sa.ForeignKeyConstraint(['attendee_id'], ['attendee.id'], name='fk_marketplace_application_attendee_id_attendee', ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name='pk_marketplace_application')
    )
    op.drop_table('artist_marketplace_application')
