"""Initial migration

Revision ID: 826e6c309c31
Revises: 1ed43776064f
Create Date: 2017-04-24 09:34:47.564099

"""


# revision identifiers, used by Alembic.
revision = '826e6c309c31'
down_revision = '1ed43776064f'
branch_labels = ('mivs',)
depends_on = None

from alembic import op
import sqlalchemy as sa
import sideboard.lib.sa


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
    op.create_table('indie_studio',
    sa.Column('id', sideboard.lib.sa.UUID(), nullable=False),
    sa.Column('group_id', sideboard.lib.sa.UUID(), nullable=True),
    sa.Column('name', sa.Unicode(), server_default='', nullable=False),
    sa.Column('address', sa.Unicode(), server_default='', nullable=False),
    sa.Column('website', sa.Unicode(), server_default='', nullable=False),
    sa.Column('twitter', sa.Unicode(), server_default='', nullable=False),
    sa.Column('facebook', sa.Unicode(), server_default='', nullable=False),
    sa.Column('status', sa.Integer(), server_default='239694250', nullable=False),
    sa.Column('staff_notes', sa.Unicode(), server_default='', nullable=False),
    sa.Column('registered', sideboard.lib.sa.UTCDateTime(), server_default=sa.text(utcnow_server_default), nullable=False),
    sa.ForeignKeyConstraint(['group_id'], ['group.id'], name=op.f('fk_indie_studio_group_id_group')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_indie_studio')),
    sa.UniqueConstraint('name', name=op.f('uq_indie_studio_name'))
    )
    op.create_table('indie_developer',
    sa.Column('id', sideboard.lib.sa.UUID(), nullable=False),
    sa.Column('studio_id', sideboard.lib.sa.UUID(), nullable=False),
    sa.Column('primary_contact', sa.Boolean(), server_default='False', nullable=False),
    sa.Column('first_name', sa.Unicode(), server_default='', nullable=False),
    sa.Column('last_name', sa.Unicode(), server_default='', nullable=False),
    sa.Column('email', sa.Unicode(), server_default='', nullable=False),
    sa.Column('cellphone', sa.Unicode(), server_default='', nullable=False),
    sa.ForeignKeyConstraint(['studio_id'], ['indie_studio.id'], name=op.f('fk_indie_developer_studio_id_indie_studio')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_indie_developer'))
    )
    op.create_table('indie_game',
    sa.Column('id', sideboard.lib.sa.UUID(), nullable=False),
    sa.Column('studio_id', sideboard.lib.sa.UUID(), nullable=False),
    sa.Column('title', sa.Unicode(), server_default='', nullable=False),
    sa.Column('brief_description', sa.Unicode(), server_default='', nullable=False),
    sa.Column('genres', sa.Unicode(), server_default='', nullable=False),
    sa.Column('description', sa.Unicode(), server_default='', nullable=False),
    sa.Column('how_to_play', sa.Unicode(), server_default='', nullable=False),
    sa.Column('link_to_video', sa.Unicode(), server_default='', nullable=False),
    sa.Column('link_to_game', sa.Unicode(), server_default='', nullable=False),
    sa.Column('password_to_game', sa.Unicode(), server_default='', nullable=False),
    sa.Column('code_type', sa.Integer(), server_default='153623436', nullable=False),
    sa.Column('code_instructions', sa.Unicode(), server_default='', nullable=False),
    sa.Column('build_status', sa.Integer(), server_default='195530085', nullable=False),
    sa.Column('build_notes', sa.Unicode(), server_default='', nullable=False),
    sa.Column('shown_events', sa.Unicode(), server_default='', nullable=False),
    sa.Column('video_submitted', sa.Boolean(), server_default='False', nullable=False),
    sa.Column('submitted', sa.Boolean(), server_default='False', nullable=False),
    sa.Column('agreed_liability', sa.Boolean(), server_default='False', nullable=False),
    sa.Column('agreed_showtimes', sa.Boolean(), server_default='False', nullable=False),
    sa.Column('agreed_reminder1', sa.Boolean(), server_default='False', nullable=False),
    sa.Column('agreed_reminder2', sa.Boolean(), server_default='False', nullable=False),
    sa.Column('status', sa.Integer(), server_default='239694250', nullable=False),
    sa.Column('judge_notes', sa.Unicode(), server_default='', nullable=False),
    sa.Column('registered', sideboard.lib.sa.UTCDateTime(), server_default=sa.text(utcnow_server_default), nullable=False),
    sa.ForeignKeyConstraint(['studio_id'], ['indie_studio.id'], name=op.f('fk_indie_game_studio_id_indie_studio')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_indie_game'))
    )
    op.create_table('indie_game_screenshot',
    sa.Column('id', sideboard.lib.sa.UUID(), nullable=False),
    sa.Column('game_id', sideboard.lib.sa.UUID(), nullable=False),
    sa.Column('filename', sa.Unicode(), server_default='', nullable=False),
    sa.Column('content_type', sa.Unicode(), server_default='', nullable=False),
    sa.Column('extension', sa.Unicode(), server_default='', nullable=False),
    sa.Column('description', sa.Unicode(), server_default='', nullable=False),
    sa.ForeignKeyConstraint(['game_id'], ['indie_game.id'], name=op.f('fk_indie_game_screenshot_game_id_indie_game')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_indie_game_screenshot'))
    )
    op.create_table('indie_judge',
    sa.Column('id', sideboard.lib.sa.UUID(), nullable=False),
    sa.Column('admin_id', sideboard.lib.sa.UUID(), nullable=False),
    sa.Column('genres', sa.Unicode(), server_default='', nullable=False),
    sa.Column('staff_notes', sa.Unicode(), server_default='', nullable=False),
    sa.ForeignKeyConstraint(['admin_id'], ['admin_account.id'], name=op.f('fk_indie_judge_admin_id_admin_account')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_indie_judge'))
    )
    op.create_table('indie_game_code',
    sa.Column('id', sideboard.lib.sa.UUID(), nullable=False),
    sa.Column('game_id', sideboard.lib.sa.UUID(), nullable=False),
    sa.Column('judge_id', sideboard.lib.sa.UUID(), nullable=True),
    sa.Column('code', sa.Unicode(), server_default='', nullable=False),
    sa.Column('unlimited_use', sa.Boolean(), server_default='False', nullable=False),
    sa.Column('judge_notes', sa.Unicode(), server_default='', nullable=False),
    sa.ForeignKeyConstraint(['game_id'], ['indie_game.id'], name=op.f('fk_indie_game_code_game_id_indie_game')),
    sa.ForeignKeyConstraint(['judge_id'], ['indie_judge.id'], name=op.f('fk_indie_game_code_judge_id_indie_judge')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_indie_game_code'))
    )
    op.create_table('indie_game_review',
    sa.Column('id', sideboard.lib.sa.UUID(), nullable=False),
    sa.Column('game_id', sideboard.lib.sa.UUID(), nullable=False),
    sa.Column('judge_id', sideboard.lib.sa.UUID(), nullable=False),
    sa.Column('video_status', sa.Integer(), server_default='196944751', nullable=False),
    sa.Column('game_status', sa.Integer(), server_default='196944751', nullable=False),
    sa.Column('video_score', sa.Integer(), server_default='196944751', nullable=False),
    sa.Column('game_score', sa.Integer(), server_default='0', nullable=False),
    sa.Column('video_review', sa.Unicode(), server_default='', nullable=False),
    sa.Column('game_review', sa.Unicode(), server_default='', nullable=False),
    sa.Column('developer_response', sa.Unicode(), server_default='', nullable=False),
    sa.Column('staff_notes', sa.Unicode(), server_default='', nullable=False),
    sa.ForeignKeyConstraint(['game_id'], ['indie_game.id'], name=op.f('fk_indie_game_review_game_id_indie_game')),
    sa.ForeignKeyConstraint(['judge_id'], ['indie_judge.id'], name=op.f('fk_indie_game_review_judge_id_indie_judge')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_indie_game_review')),
    sa.UniqueConstraint('game_id', 'judge_id', name='review_game_judge_uniq')
    )


def downgrade():
    op.drop_table('indie_game_review')
    op.drop_table('indie_game_code')
    op.drop_table('indie_judge')
    op.drop_table('indie_game_screenshot')
    op.drop_table('indie_game')
    op.drop_table('indie_developer')
    op.drop_table('indie_studio')
