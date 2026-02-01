"""Initial migration

Revision ID: ff7e7ae6d711
Revises:
Create Date: 2017-04-23 19:06:15.552092

"""


# revision identifiers, used by Alembic.
revision = 'ff7e7ae6d711'
down_revision = None
branch_labels = ('uber',)
depends_on = None

from alembic import op
import sqlalchemy as sa


try:
    is_sqlite = op.get_context().dialect.name == 'sqlite'
except Exception:
    is_sqlite = False

if is_sqlite:
    op.get_context().connection.execute('PRAGMA foreign_keys=ON;')
    utcnow_server_default = "(datetime('now', 'utc'))"
else:
    utcnow_server_default = "timezone('utc', current_timestamp)"


def upgrade():
    op.create_table('approved_email',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('ident', sa.Unicode(), server_default='', nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_approved_email'))
    )
    op.create_table('arbitrary_charge',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('amount', sa.Integer(), nullable=False),
    sa.Column('what', sa.Unicode(), server_default='', nullable=False),
    sa.Column('when', sa.DateTime(timezone=True), nullable=False),
    sa.Column('reg_station', sa.Integer(), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_arbitrary_charge'))
    )
    op.create_table('email',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('fk_id', sa.Uuid(as_uuid=False), nullable=True),
    sa.Column('ident', sa.Unicode(), server_default='', nullable=False),
    sa.Column('model', sa.Unicode(), server_default='', nullable=False),
    sa.Column('when', sa.DateTime(timezone=True), nullable=False),
    sa.Column('subject', sa.Unicode(), server_default='', nullable=False),
    sa.Column('dest', sa.Unicode(), server_default='', nullable=False),
    sa.Column('body', sa.Unicode(), server_default='', nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_email'))
    )
    op.create_table('group',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('public_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('name', sa.Unicode(), server_default='', nullable=False),
    sa.Column('tables', sa.Numeric(), server_default='0', nullable=False),
    sa.Column('address', sa.Unicode(), server_default='', nullable=False),
    sa.Column('website', sa.Unicode(), server_default='', nullable=False),
    sa.Column('wares', sa.Unicode(), server_default='', nullable=False),
    sa.Column('description', sa.Unicode(), server_default='', nullable=False),
    sa.Column('special_needs', sa.Unicode(), server_default='', nullable=False),
    sa.Column('amount_paid', sa.Integer(), server_default='0', nullable=False),
    sa.Column('amount_refunded', sa.Integer(), server_default='0', nullable=False),
    sa.Column('cost', sa.Integer(), server_default='0', nullable=False),
    sa.Column('auto_recalc', sa.Boolean(), server_default='True', nullable=False),
    sa.Column('can_add', sa.Boolean(), server_default='False', nullable=False),
    sa.Column('admin_notes', sa.Unicode(), server_default='', nullable=False),
    sa.Column('status', sa.Integer(), server_default='172070601', nullable=False),
    sa.Column('registered', sa.DateTime(timezone=True), server_default=sa.text(utcnow_server_default), nullable=False),
    sa.Column('approved', sa.DateTime(timezone=True), nullable=True),
    sa.Column('leader_id', sa.Uuid(as_uuid=False), nullable=True),
    sa.ForeignKeyConstraint(['leader_id'], ['attendee.id'], name='fk_leader', use_alter=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_group'))
    )
    op.create_table('job',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('type', sa.Integer(), server_default='252034462', nullable=False),
    sa.Column('name', sa.Unicode(), server_default='', nullable=False),
    sa.Column('description', sa.Unicode(), server_default='', nullable=False),
    sa.Column('location', sa.Integer(), nullable=False),
    sa.Column('start_time', sa.DateTime(timezone=True), nullable=False),
    sa.Column('duration', sa.Integer(), nullable=False),
    sa.Column('weight', sa.Float(), server_default='1', nullable=False),
    sa.Column('slots', sa.Integer(), nullable=False),
    sa.Column('restricted', sa.Boolean(), server_default='False', nullable=False),
    sa.Column('extra15', sa.Boolean(), server_default='False', nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_job'))
    )
    op.create_table('page_view_tracking',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('when', sa.DateTime(timezone=True), nullable=False),
    sa.Column('who', sa.Unicode(), server_default='', nullable=False),
    sa.Column('page', sa.Unicode(), server_default='', nullable=False),
    sa.Column('what', sa.Unicode(), server_default='', nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_page_view_tracking'))
    )
    op.create_table('tracking',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('fk_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('model', sa.Unicode(), server_default='', nullable=False),
    sa.Column('when', sa.DateTime(timezone=True), nullable=False),
    sa.Column('who', sa.Unicode(), server_default='', nullable=False),
    sa.Column('page', sa.Unicode(), server_default='', nullable=False),
    sa.Column('which', sa.Unicode(), server_default='', nullable=False),
    sa.Column('links', sa.Unicode(), server_default='', nullable=False),
    sa.Column('action', sa.Integer(), nullable=False),
    sa.Column('data', sa.Unicode(), server_default='', nullable=False),
    sa.Column('snapshot', sa.Unicode(), server_default='', nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_tracking'))
    )
    op.create_index(op.f('ix_tracking_fk_id'), 'tracking', ['fk_id'], unique=False)
    op.create_table('watch_list',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('first_names', sa.Unicode(), server_default='', nullable=False),
    sa.Column('last_name', sa.Unicode(), server_default='', nullable=False),
    sa.Column('email', sa.Unicode(), server_default='', nullable=False),
    sa.Column('birthdate', sa.Date(), nullable=True),
    sa.Column('reason', sa.Unicode(), server_default='', nullable=False),
    sa.Column('action', sa.Unicode(), server_default='', nullable=False),
    sa.Column('active', sa.Boolean(), server_default='True', nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_watch_list'))
    )
    op.create_table('attendee',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('watchlist_id', sa.Uuid(as_uuid=False), nullable=True),
    sa.Column('group_id', sa.Uuid(as_uuid=False), nullable=True),
    sa.Column('placeholder', sa.Boolean(), server_default='False', nullable=False),
    sa.Column('first_name', sa.Unicode(), server_default='', nullable=False),
    sa.Column('last_name', sa.Unicode(), server_default='', nullable=False),
    sa.Column('legal_name', sa.Unicode(), server_default='', nullable=False),
    sa.Column('email', sa.Unicode(), server_default='', nullable=False),
    sa.Column('birthdate', sa.Date(), nullable=True),
    sa.Column('age_group', sa.Integer(), server_default='178244408', nullable=True),
    sa.Column('international', sa.Boolean(), server_default='False', nullable=False),
    sa.Column('zip_code', sa.Unicode(), server_default='', nullable=False),
    sa.Column('address1', sa.Unicode(), server_default='', nullable=False),
    sa.Column('address2', sa.Unicode(), server_default='', nullable=False),
    sa.Column('city', sa.Unicode(), server_default='', nullable=False),
    sa.Column('region', sa.Unicode(), server_default='', nullable=False),
    sa.Column('country', sa.Unicode(), server_default='', nullable=False),
    sa.Column('no_cellphone', sa.Boolean(), server_default='False', nullable=False),
    sa.Column('ec_name', sa.Unicode(), server_default='', nullable=False),
    sa.Column('ec_phone', sa.Unicode(), server_default='', nullable=False),
    sa.Column('cellphone', sa.Unicode(), server_default='', nullable=False),
    sa.Column('interests', sa.Unicode(), server_default='', nullable=False),
    sa.Column('found_how', sa.Unicode(), server_default='', nullable=False),
    sa.Column('comments', sa.Unicode(), server_default='', nullable=False),
    sa.Column('for_review', sa.Unicode(), server_default='', nullable=False),
    sa.Column('admin_notes', sa.Unicode(), server_default='', nullable=False),
    sa.Column('public_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('badge_num', sa.Integer(), nullable=True),
    sa.Column('badge_type', sa.Integer(), server_default='51352218', nullable=False),
    sa.Column('badge_status', sa.Integer(), server_default='163076611', nullable=False),
    sa.Column('ribbon', sa.Integer(), server_default='154973361', nullable=False),
    sa.Column('affiliate', sa.Unicode(), server_default='', nullable=False),
    sa.Column('shirt', sa.Integer(), server_default='0', nullable=False),
    sa.Column('can_spam', sa.Boolean(), server_default='False', nullable=False),
    sa.Column('regdesk_info', sa.Unicode(), server_default='', nullable=False),
    sa.Column('extra_merch', sa.Unicode(), server_default='', nullable=False),
    sa.Column('got_merch', sa.Boolean(), server_default='False', nullable=False),
    sa.Column('reg_station', sa.Integer(), nullable=True),
    sa.Column('registered', sa.DateTime(timezone=True), server_default=sa.text(utcnow_server_default), nullable=False),
    sa.Column('checked_in', sa.DateTime(timezone=True), nullable=True),
    sa.Column('paid', sa.Integer(), server_default='121378471', nullable=False),
    sa.Column('overridden_price', sa.Integer(), nullable=True),
    sa.Column('amount_paid', sa.Integer(), server_default='0', nullable=False),
    sa.Column('amount_extra', sa.Integer(), server_default='0', nullable=False),
    sa.Column('payment_method', sa.Integer(), nullable=True),
    sa.Column('amount_refunded', sa.Integer(), server_default='0', nullable=False),
    sa.Column('badge_printed_name', sa.Unicode(), server_default='', nullable=False),
    sa.Column('staffing', sa.Boolean(), server_default='False', nullable=False),
    sa.Column('requested_depts', sa.Unicode(), server_default='', nullable=False),
    sa.Column('assigned_depts', sa.Unicode(), server_default='', nullable=False),
    sa.Column('trusted_depts', sa.Unicode(), server_default='', nullable=False),
    sa.Column('nonshift_hours', sa.Integer(), server_default='0', nullable=False),
    sa.Column('past_years', sa.Unicode(), server_default='', nullable=False),
    sa.Column('can_work_setup', sa.Boolean(), server_default='False', nullable=False),
    sa.Column('can_work_teardown', sa.Boolean(), server_default='False', nullable=False),
    sa.ForeignKeyConstraint(['group_id'], ['group.id'], name=op.f('fk_attendee_group_id_group'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['watchlist_id'], ['watch_list.id'], name=op.f('fk_attendee_watchlist_id_watch_list'), ondelete='set null'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_attendee')),
    *[c for c in [sa.UniqueConstraint('badge_num', deferrable='True', initially='DEFERRED', name=op.f('uq_attendee_badge_num'))] if not is_sqlite]
    )
    op.create_table('admin_account',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('attendee_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('hashed', sa.Unicode(), server_default='', nullable=False),
    sa.Column('access', sa.Unicode(), server_default='', nullable=False),
    sa.ForeignKeyConstraint(['attendee_id'], ['attendee.id'], name=op.f('fk_admin_account_attendee_id_attendee')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_admin_account')),
    sa.UniqueConstraint('attendee_id', name=op.f('uq_admin_account_attendee_id'))
    )
    op.create_table('dept_checklist_item',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('attendee_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('slug', sa.Unicode(), server_default='', nullable=False),
    sa.Column('comments', sa.Unicode(), server_default='', nullable=False),
    sa.ForeignKeyConstraint(['attendee_id'], ['attendee.id'], name=op.f('fk_dept_checklist_item_attendee_id_attendee')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_dept_checklist_item')),
    sa.UniqueConstraint('attendee_id', 'slug', name='_dept_checklist_item_uniq')
    )
    op.create_table('food_restrictions',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('attendee_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('standard', sa.Unicode(), server_default='', nullable=False),
    sa.Column('sandwich_pref', sa.Unicode(), server_default='', nullable=False),
    sa.Column('freeform', sa.Unicode(), server_default='', nullable=False),
    sa.ForeignKeyConstraint(['attendee_id'], ['attendee.id'], name=op.f('fk_food_restrictions_attendee_id_attendee')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_food_restrictions')),
    sa.UniqueConstraint('attendee_id', name=op.f('uq_food_restrictions_attendee_id'))
    )
    op.create_table('m_points_for_cash',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('attendee_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('amount', sa.Integer(), nullable=False),
    sa.Column('when', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['attendee_id'], ['attendee.id'], name=op.f('fk_m_points_for_cash_attendee_id_attendee')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_m_points_for_cash'))
    )
    op.create_table('merch_discount',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('attendee_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('uses', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['attendee_id'], ['attendee.id'], name=op.f('fk_merch_discount_attendee_id_attendee')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_merch_discount')),
    sa.UniqueConstraint('attendee_id', name=op.f('uq_merch_discount_attendee_id'))
    )
    op.create_table('merch_pickup',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('picked_up_by_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('picked_up_for_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.ForeignKeyConstraint(['picked_up_by_id'], ['attendee.id'], name=op.f('fk_merch_pickup_picked_up_by_id_attendee')),
    sa.ForeignKeyConstraint(['picked_up_for_id'], ['attendee.id'], name=op.f('fk_merch_pickup_picked_up_for_id_attendee')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_merch_pickup')),
    sa.UniqueConstraint('picked_up_for_id', name=op.f('uq_merch_pickup_picked_up_for_id'))
    )
    op.create_table('no_shirt',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('attendee_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.ForeignKeyConstraint(['attendee_id'], ['attendee.id'], name=op.f('fk_no_shirt_attendee_id_attendee')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_no_shirt')),
    sa.UniqueConstraint('attendee_id', name=op.f('uq_no_shirt_attendee_id'))
    )
    op.create_table('old_m_point_exchange',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('attendee_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('amount', sa.Integer(), nullable=False),
    sa.Column('when', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['attendee_id'], ['attendee.id'], name=op.f('fk_old_m_point_exchange_attendee_id_attendee')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_old_m_point_exchange'))
    )
    op.create_table('sale',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('attendee_id', sa.Uuid(as_uuid=False), nullable=True),
    sa.Column('what', sa.Unicode(), server_default='', nullable=False),
    sa.Column('cash', sa.Integer(), server_default='0', nullable=False),
    sa.Column('mpoints', sa.Integer(), server_default='0', nullable=False),
    sa.Column('when', sa.DateTime(timezone=True), nullable=False),
    sa.Column('reg_station', sa.Integer(), nullable=True),
    sa.Column('payment_method', sa.Integer(), server_default='251700478', nullable=False),
    sa.ForeignKeyConstraint(['attendee_id'], ['attendee.id'], name=op.f('fk_sale_attendee_id_attendee'), ondelete='set null'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_sale'))
    )
    op.create_table('shift',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('job_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('attendee_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('worked', sa.Integer(), server_default='176686787', nullable=False),
    sa.Column('rating', sa.Integer(), server_default='54944008', nullable=False),
    sa.Column('comment', sa.Unicode(), server_default='', nullable=False),
    sa.ForeignKeyConstraint(['attendee_id'], ['attendee.id'], name=op.f('fk_shift_attendee_id_attendee'), ondelete='cascade'),
    sa.ForeignKeyConstraint(['job_id'], ['job.id'], name=op.f('fk_shift_job_id_job'), ondelete='cascade'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_shift'))
    )
    op.create_table('password_reset',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('account_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('generated', sa.DateTime(timezone=True), server_default=sa.text(utcnow_server_default), nullable=False),
    sa.Column('hashed', sa.Unicode(), server_default='', nullable=False),
    sa.ForeignKeyConstraint(['account_id'], ['admin_account.id'], name=op.f('fk_password_reset_account_id_admin_account')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_password_reset')),
    sa.UniqueConstraint('account_id', name=op.f('uq_password_reset_account_id'))
    )


def downgrade():
    op.drop_table('password_reset')
    op.drop_table('shift')
    op.drop_table('sale')
    op.drop_table('old_m_point_exchange')
    op.drop_table('no_shirt')
    op.drop_table('merch_pickup')
    op.drop_table('merch_discount')
    op.drop_table('m_points_for_cash')
    op.drop_table('food_restrictions')
    op.drop_table('dept_checklist_item')
    op.drop_table('admin_account')
    op.drop_table('attendee')
    op.drop_table('watch_list')
    op.drop_index(op.f('ix_tracking_fk_id'), table_name='tracking')
    op.drop_table('tracking')
    op.drop_table('page_view_tracking')
    op.drop_table('job')
    op.drop_table('group')
    op.drop_table('email')
    op.drop_table('arbitrary_charge')
    op.drop_table('approved_email')
