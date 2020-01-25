"""Initial migration

Revision ID: fc791d73e762
Revises: 416eb615ff1a
Create Date: 2017-04-23 19:14:43.751659

"""


# revision identifiers, used by Alembic.
revision = 'fc791d73e762'
down_revision = '416eb615ff1a'
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
    op.create_table('band',
    sa.Column('id', residue.UUID(), nullable=False),
    sa.Column('group_id', residue.UUID(), nullable=False),
    sa.Column('event_id', residue.UUID(), nullable=True),
    sa.Column('payment', sa.Integer(), server_default='0', nullable=False),
    sa.Column('vehicles', sa.Integer(), server_default='1', nullable=False),
    sa.Column('estimated_loadin_minutes', sa.Integer(), server_default='20', nullable=False),
    sa.Column('estimated_performance_minutes', sa.Integer(), server_default='40', nullable=False),
    sa.ForeignKeyConstraint(['event_id'], ['event.id'], name=op.f('fk_band_event_id_event')),
    sa.ForeignKeyConstraint(['group_id'], ['group.id'], name=op.f('fk_band_group_id_group')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_band'))
    )
    op.create_table('band_bio',
    sa.Column('id', residue.UUID(), nullable=False),
    sa.Column('band_id', residue.UUID(), nullable=False),
    sa.Column('desc', sa.Unicode(), server_default='', nullable=False),
    sa.Column('website', sa.Unicode(), server_default='', nullable=False),
    sa.Column('facebook', sa.Unicode(), server_default='', nullable=False),
    sa.Column('twitter', sa.Unicode(), server_default='', nullable=False),
    sa.Column('other_social_media', sa.Unicode(), server_default='', nullable=False),
    sa.Column('pic_filename', sa.Unicode(), server_default='', nullable=False),
    sa.Column('pic_content_type', sa.Unicode(), server_default='', nullable=False),
    sa.ForeignKeyConstraint(['band_id'], ['band.id'], name=op.f('fk_band_bio_band_id_band')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_band_bio')),
    sa.UniqueConstraint('band_id', name=op.f('uq_band_bio_band_id'))
    )
    op.create_table('band_charity',
    sa.Column('id', residue.UUID(), nullable=False),
    sa.Column('band_id', residue.UUID(), nullable=False),
    sa.Column('donating', sa.Integer(), nullable=True),
    sa.Column('desc', sa.Unicode(), server_default='', nullable=False),
    sa.ForeignKeyConstraint(['band_id'], ['band.id'], name=op.f('fk_band_charity_band_id_band')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_band_charity')),
    sa.UniqueConstraint('band_id', name=op.f('uq_band_charity_band_id'))
    )
    op.create_table('band_info',
    sa.Column('id', residue.UUID(), nullable=False),
    sa.Column('band_id', residue.UUID(), nullable=False),
    sa.Column('poc_phone', sa.Unicode(), server_default='', nullable=False),
    sa.Column('performer_count', sa.Integer(), server_default='0', nullable=False),
    sa.Column('bringing_vehicle', sa.Boolean(), server_default='False', nullable=False),
    sa.Column('vehicle_info', sa.Unicode(), server_default='', nullable=False),
    sa.Column('arrival_time', sa.Unicode(), server_default='', nullable=False),
    sa.ForeignKeyConstraint(['band_id'], ['band.id'], name=op.f('fk_band_info_band_id_band')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_band_info')),
    sa.UniqueConstraint('band_id', name=op.f('uq_band_info_band_id'))
    )
    op.create_table('band_merch',
    sa.Column('id', residue.UUID(), nullable=False),
    sa.Column('band_id', residue.UUID(), nullable=False),
    sa.Column('selling_merch', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['band_id'], ['band.id'], name=op.f('fk_band_merch_band_id_band')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_band_merch')),
    sa.UniqueConstraint('band_id', name=op.f('uq_band_merch_band_id'))
    )
    op.create_table('band_panel',
    sa.Column('id', residue.UUID(), nullable=False),
    sa.Column('band_id', residue.UUID(), nullable=False),
    sa.Column('wants_panel', sa.Integer(), nullable=True),
    sa.Column('name', sa.Unicode(), server_default='', nullable=False),
    sa.Column('length', sa.Unicode(), server_default='', nullable=False),
    sa.Column('desc', sa.Unicode(), server_default='', nullable=False),
    sa.Column('tech_needs', sa.Unicode(), server_default='', nullable=False),
    sa.ForeignKeyConstraint(['band_id'], ['band.id'], name=op.f('fk_band_panel_band_id_band')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_band_panel')),
    sa.UniqueConstraint('band_id', name=op.f('uq_band_panel_band_id'))
    )
    op.create_table('band_stage_plot',
    sa.Column('id', residue.UUID(), nullable=False),
    sa.Column('band_id', residue.UUID(), nullable=False),
    sa.Column('filename', sa.Unicode(), server_default='', nullable=False),
    sa.Column('content_type', sa.Unicode(), server_default='', nullable=False),
    sa.ForeignKeyConstraint(['band_id'], ['band.id'], name=op.f('fk_band_stage_plot_band_id_band')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_band_stage_plot')),
    sa.UniqueConstraint('band_id', name=op.f('uq_band_stage_plot_band_id'))
    )
    op.create_table('band_taxes',
    sa.Column('id', residue.UUID(), nullable=False),
    sa.Column('band_id', residue.UUID(), nullable=False),
    sa.Column('w9_filename', sa.Unicode(), server_default='', nullable=False),
    sa.Column('w9_content_type', sa.Unicode(), server_default='', nullable=False),
    sa.ForeignKeyConstraint(['band_id'], ['band.id'], name=op.f('fk_band_taxes_band_id_band')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_band_taxes')),
    sa.UniqueConstraint('band_id', name=op.f('uq_band_taxes_band_id'))
    )


def downgrade():
    op.drop_table('band_taxes')
    op.drop_table('band_stage_plot')
    op.drop_table('band_panel')
    op.drop_table('band_merch')
    op.drop_table('band_info')
    op.drop_table('band_charity')
    op.drop_table('band_bio')
    op.drop_table('band')
