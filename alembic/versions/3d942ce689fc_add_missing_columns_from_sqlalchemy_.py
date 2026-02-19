"""Add missing columns from SQLAlchemy upgrade

Revision ID: 3d942ce689fc
Revises: 5a0e898174d4
Create Date: 2026-02-05 16:34:19.803186

"""


# revision identifiers, used by Alembic.
revision = '3d942ce689fc'
down_revision = '5a0e898174d4'
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
    op.add_column('panel_applicant', sa.Column('social_media_info', sa.String(), server_default='', nullable=False))
    op.drop_column('panel_applicant', 'social_media')
    op.drop_index(op.f('uq_promo_code_word_normalized_word_part_of_speech'), table_name='promo_code_word')
    op.create_index('uq_promo_code_word_normalized_word_part_of_speech', 'promo_code_word', [sa.literal_column('lower(trim(word))'), 'part_of_speech'], unique=True)


def downgrade():
    op.drop_index('uq_promo_code_word_normalized_word_part_of_speech', table_name='promo_code_word')
    op.create_index(op.f('uq_promo_code_word_normalized_word_part_of_speech'), 'promo_code_word', [sa.literal_column('lower(TRIM(BOTH FROM word))'), 'part_of_speech'], unique=True)
    op.add_column('panel_applicant', sa.Column('social_media', postgresql.JSON(astext_type=sa.Text()), server_default=sa.text("'{}'::json"), autoincrement=False, nullable=False))
    op.drop_column('panel_applicant', 'social_media_info')
