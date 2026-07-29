"""Add receipt discount table

Revision ID: 2a871fd47f03
Revises: 4885cb7df802
Create Date: 2026-06-17 20:31:59.874514

"""


# revision identifiers, used by Alembic.
revision = '2a871fd47f03'
down_revision = '4885cb7df802'
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
    op.create_table('receipt_discount',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('created', sa.DateTime(timezone=True), server_default=sa.text("timezone('utc', current_timestamp)"), nullable=False),
    sa.Column('last_updated', sa.DateTime(timezone=True), server_default=sa.text("timezone('utc', current_timestamp)"), nullable=False),
    sa.Column('external_id', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('last_synced', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('added', sa.DateTime(timezone=True), server_default=sa.text("timezone('utc', current_timestamp)"), nullable=False),
    sa.Column('receipt_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('promo_code_id', sa.Uuid(as_uuid=False), nullable=True),
    sa.Column('department', sa.Integer(), server_default='100673436', nullable=False),
    sa.Column('category', sa.Integer(), server_default='224685583', nullable=False),
    sa.Column('desc', sa.Unicode(), server_default='', nullable=False),
    sa.Column('who', sa.Unicode(), server_default='', nullable=False),
    sa.Column('discount', sa.Integer(), nullable=True),
    sa.Column('applicable_discount', sa.Integer(), server_default='0', nullable=False),
    sa.Column('discount_str', sa.Unicode(), server_default='', nullable=False),
    sa.Column('discount_type', sa.Integer(), server_default='268131930', nullable=False),
    sa.Column('discount_on', sa.Integer(), server_default='125517225', nullable=False),
    sa.ForeignKeyConstraint(['promo_code_id'], ['promo_code.id'], name=op.f('fk_receipt_discount_promo_code_id_promo_code')),
    sa.ForeignKeyConstraint(['receipt_id'], ['model_receipt.id'], name=op.f('fk_receipt_discount_receipt_id_model_receipt'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_receipt_discount'))
    )
    op.create_index(op.f('ix_receipt_discount_promo_code_id'), 'receipt_discount', ['promo_code_id'], unique=False)
    op.add_column('promo_code', sa.Column('discount_on', sa.Unicode(), server_default='125517225', nullable=False))
    op.add_column('promo_code', sa.Column('department', sa.Integer(), server_default='100673436', nullable=False))
    


def downgrade():
    op.drop_column('promo_code', 'discount_on')
    op.drop_column('promo_code', 'department')
    op.drop_index(op.f('ix_receipt_discount_promo_code_id'), table_name='receipt_discount')
    op.drop_table('receipt_discount')
