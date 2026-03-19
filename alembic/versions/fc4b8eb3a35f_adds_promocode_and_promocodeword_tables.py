"""Adds PromoCode and PromoCodeWord tables

Revision ID: fc4b8eb3a35f
Revises: 3723d12f8740
Create Date: 2017-05-31 14:22:11.126999

"""


# revision identifiers, used by Alembic.
revision = 'fc4b8eb3a35f'
down_revision = '3723d12f8740'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql.expression import text


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
    op.create_table('promo_code',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('code', sa.Unicode(), server_default='', nullable=False),
    sa.Column('discount', sa.Integer(), nullable=True),
    sa.Column('discount_type', sa.Integer(), server_default='0', nullable=False),
    sa.Column('expiration_date', sa.DateTime(timezone=True), nullable=False),
    sa.Column('uses_allowed', sa.Integer(), nullable=True),
    sa.CheckConstraint("trim(code) != ''", name='ck_promo_code_non_empty_code'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_promo_code'))
    )
    op.create_table('promo_code_word',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('word', sa.Unicode(), server_default='', nullable=False),
    sa.Column('part_of_speech', sa.Integer(), server_default='0', nullable=False),
    sa.CheckConstraint("trim(word) != ''", name='ck_promo_code_word_non_empty_word'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_promo_code_word'))
    )

    if is_sqlite:
        def listen_for_reflect(inspector, table, column_info):
            """Adds parenthesis around SQLite datetime defaults for utcnow."""
            if column_info['default'] == "datetime('now', 'utc')":
                column_info['default'] = utcnow_server_default

        with op.batch_alter_table(
                'attendee',
                reflect_kwargs=dict(listeners=[('column_reflect', listen_for_reflect)])) as batch_op:
            batch_op.add_column(sa.Column('promo_code_id', sa.Uuid(as_uuid=False), nullable=True))
            batch_op.create_foreign_key(op.f('fk_attendee_promo_code_id_promo_code'), 'promo_code', ['promo_code_id'], ['id'])
    else:
        op.add_column('attendee', sa.Column('promo_code_id', sa.Uuid(as_uuid=False), nullable=True))
        op.create_foreign_key(op.f('fk_attendee_promo_code_id_promo_code'), 'attendee', 'promo_code', ['promo_code_id'], ['id'])

    op.create_index(op.f('ix_attendee_promo_code_id'), 'attendee', ['promo_code_id'], unique=False)

    op.create_index(
        op.f('uq_promo_code_normalized_code'),
        'promo_code',
        [text("replace(replace(lower(code), '-', ''), ' ', '')")],
        unique=True)

    op.create_index(
        op.f('uq_promo_code_word_normalized_word_part_of_speech'),
        'promo_code_word',
        [text('lower(trim(word))'), 'part_of_speech'],
        unique=True)


def downgrade():
    if not is_sqlite:
        op.drop_constraint(op.f('fk_attendee_promo_code_id_promo_code'), 'attendee', type_='foreignkey')
    op.drop_index(op.f('ix_attendee_promo_code_id'), table_name='attendee')
    op.drop_index(op.f('uq_promo_code_normalized_code'), 'promo_code')
    op.drop_index(op.f('uq_promo_code_word_normalized_word_part_of_speech'), 'promo_code_word')
    op.drop_column('attendee', 'promo_code_id')
    op.drop_table('promo_code_word')
    op.drop_table('promo_code')
