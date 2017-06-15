"""Adds PromoCode unlimited use free badge constraint

Revision ID: 1355d9cc778c
Revises: fc4b8eb3a35f
Create Date: 2017-06-14 17:35:33.562523

"""


# revision identifiers, used by Alembic.
revision = '1355d9cc778c'
down_revision = 'fc4b8eb3a35f'
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
                'promo_code',
                reflect_kwargs=dict(listeners=[('column_reflect', listen_for_reflect)])) as batch_op:
            batch_op.create_check_constraint(
                op.f('ck_promo_code_non_empty_code'),
                "trim(code) != ''")
            batch_op.create_check_constraint(
                op.f('ck_promo_code_no_unlimited_use_free_badge'),
                'discount IS NOT NULL OR uses_allowed IS NOT NULL')
    else:
        op.create_check_constraint(
            op.f('ck_promo_code_no_unlimited_use_free_badge'),
            'promo_code',
            'discount IS NOT NULL OR uses_allowed IS NOT NULL')


def downgrade():
    op.drop_constraint(op.f('ck_promo_code_no_unlimited_use_free_badge'), 'promo_code')
