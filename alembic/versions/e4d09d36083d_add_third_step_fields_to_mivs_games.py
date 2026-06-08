"""Add third step fields to MIVS games

Revision ID: e4d09d36083d
Revises: c2c484e647ec
Create Date: 2017-10-17 04:35:02.999727

"""


# revision identifiers, used by Alembic.
revision = 'e4d09d36083d'
down_revision = 'c2c484e647ec'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


try:
    is_sqlite = op.get_context().dialect.name == 'sqlite'
except:
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
    op.rename_table('indie_game_screenshot', 'indie_game_image')
    if is_sqlite:
        with op.batch_alter_table('indie_game_image', reflect_kwargs=sqlite_reflect_kwargs) as batch_op:
            batch_op.add_column(sa.Column('is_screenshot', sa.Boolean(), server_default='True', nullable=False))
            batch_op.add_column(sa.Column('use_in_promo', sa.Boolean(), server_default='False', nullable=False))

            batch_op.drop_constraint('fk_indie_game_screenshot_game_id_indie_game', type_='foreignkey')
            batch_op.create_foreign_key(op.f('fk_indie_game_image_game_id_indie_game'), 'indie_game', ['game_id'], ['id'])

            batch_op.drop_constraint('pk_indie_game_screenshot', type_='primary')
            batch_op.create_primary_key(op.f('pk_indie_game_image'), ['id'])


        with op.batch_alter_table('indie_game', reflect_kwargs=sqlite_reflect_kwargs) as batch_op:
            batch_op.add_column(sa.Column('facebook', sa.Unicode(), server_default='', nullable=False))
            batch_op.add_column(sa.Column('has_multiplayer', sa.Boolean(), server_default='False', nullable=False))
            batch_op.add_column(sa.Column('leaderboard_challenge', sa.Boolean(), server_default='False', nullable=False))
            batch_op.add_column(sa.Column('link_to_promo_video', sa.Unicode(), server_default='', nullable=False))
            batch_op.add_column(sa.Column('link_to_webpage', sa.Unicode(), server_default='', nullable=False))
            batch_op.add_column(sa.Column('multiplayer_game_length', sa.Integer(), nullable=True))
            batch_op.add_column(sa.Column('other_social_media', sa.Unicode(), server_default='', nullable=False))
            batch_op.add_column(sa.Column('player_count', sa.Unicode(), server_default='', nullable=False))
            batch_op.add_column(sa.Column('tournament_at_event', sa.Boolean(), server_default='False', nullable=False))
            batch_op.add_column(sa.Column('tournament_prizes', sa.Unicode(), server_default='', nullable=False))
            batch_op.add_column(sa.Column('twitter', sa.Unicode(), server_default='', nullable=False))
    else:
        op.add_column('indie_game_image', sa.Column('is_screenshot', sa.Boolean(), server_default='True', nullable=False))
        op.add_column('indie_game_image', sa.Column('use_in_promo', sa.Boolean(), server_default='False', nullable=False))

        op.drop_constraint('fk_indie_game_screenshot_game_id_indie_game', 'indie_game_image', type_='foreignkey')
        op.create_foreign_key(op.f('fk_indie_game_image_game_id_indie_game'), 'indie_game_image', 'indie_game', ['game_id'], ['id'])

        op.drop_constraint('pk_indie_game_screenshot', 'indie_game_image', type_='primary')
        op.create_primary_key(op.f('pk_indie_game_image'), 'indie_game_image', ['id'])

        op.add_column('indie_game', sa.Column('facebook', sa.Unicode(), server_default='', nullable=False))
        op.add_column('indie_game', sa.Column('has_multiplayer', sa.Boolean(), server_default='False', nullable=False))
        op.add_column('indie_game', sa.Column('leaderboard_challenge', sa.Boolean(), server_default='False', nullable=False))
        op.add_column('indie_game', sa.Column('link_to_promo_video', sa.Unicode(), server_default='', nullable=False))
        op.add_column('indie_game', sa.Column('link_to_webpage', sa.Unicode(), server_default='', nullable=False))
        op.add_column('indie_game', sa.Column('multiplayer_game_length', sa.Integer(), nullable=True))
        op.add_column('indie_game', sa.Column('other_social_media', sa.Unicode(), server_default='', nullable=False))
        op.add_column('indie_game', sa.Column('player_count', sa.Unicode(), server_default='', nullable=False))
        op.add_column('indie_game', sa.Column('tournament_at_event', sa.Boolean(), server_default='False', nullable=False))
        op.add_column('indie_game', sa.Column('tournament_prizes', sa.Unicode(), server_default='', nullable=False))
        op.add_column('indie_game', sa.Column('twitter', sa.Unicode(), server_default='', nullable=False))


def downgrade():
    op.drop_column('indie_game_image', 'use_in_promo')
    op.drop_column('indie_game_image', 'is_screenshot')
    op.rename_table('indie_game_image', 'indie_game_screenshot')
    op.drop_column('indie_game', 'twitter')
    op.drop_column('indie_game', 'tournament_prizes')
    op.drop_column('indie_game', 'tournament_at_event')
    op.drop_column('indie_game', 'player_count')
    op.drop_column('indie_game', 'other_social_media')
    op.drop_column('indie_game', 'multiplayer_game_length')
    op.drop_column('indie_game', 'link_to_webpage')
    op.drop_column('indie_game', 'link_to_promo_video')
    op.drop_column('indie_game', 'leaderboard_challenge')
    op.drop_column('indie_game', 'has_multiplayer')
    op.drop_column('indie_game', 'facebook')
