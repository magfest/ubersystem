"""Adds rock island inventory

Revision ID: 9e3e15a7cf59
Revises: 27a3a3676666
Create Date: 2017-09-23 16:26:14.896484

"""


# revision identifiers, used by Alembic.
revision = '9e3e15a7cf59'
down_revision = '27a3a3676666'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa
from sqlalchemy.types import JSON
from sqlalchemy.ext.mutable import MutableDict


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
    # Leftover renaming from the bands -> guests refactor
    from sqlalchemy.engine import reflection
    inspector = reflection.Inspector(op.get_bind())

    foreignkeys_to_drop = [
        ['guest_group', ['fk_band_event_id_event', 'fk_band_group_id_group']],
        ['guest_bio', ['band_bio_band_id_key', 'fk_band_bio_band_id_band']],
        ['guest_charity', ['band_charity_band_id_key', 'fk_band_charity_band_id_band']],
        ['guest_info', ['band_info_band_id_key', 'fk_band_info_band_id_band']],
        ['guest_merch', ['band_merch_band_id_key', 'fk_band_merch_band_id_band']],
        ['guest_panel', ['band_panel_band_id_key', 'fk_band_panel_band_id_band']],
        ['guest_stage_plot', ['band_stage_plot_band_id_key', 'fk_band_stage_plot_band_id_band']],
        ['guest_taxes', ['band_taxes_band_id_key', 'fk_band_taxes_band_id_band']],
        ['guest_autograph', ['fk_guest_autograph_guest_id_guest_group']],
        ['guest_interview', ['fk_guest_interview_guest_id_guest_group']],
        ['guest_travel_plans', ['fk_guest_travel_plans_guest_id_guest_group']],
    ]

    primarykeys_to_drop = [
        ['guest_group', ['pk_band']],
        ['guest_bio', ['pk_band_bio']],
        ['guest_charity', ['pk_band_charity']],
        ['guest_info', ['pk_band_info']],
        ['guest_merch', ['pk_band_merch']],
        ['guest_panel', ['pk_band_panel']],
        ['guest_stage_plot', ['pk_band_stage_plot']],
        ['guest_taxes', ['pk_band_taxes']],
    ]

    uniqueconstraints_to_drop = [
        ['guest_bio', ['uq_band_bio_band_id']],
        ['guest_charity', ['uq_band_charity_band_id']],
        ['guest_info', ['uq_band_info_band_id']],
        ['guest_merch', ['uq_band_merch_band_id']],
        ['guest_panel', ['uq_band_panel_band_id']],
        ['guest_stage_plot', ['uq_band_stage_plot_band_id']],
        ['guest_taxes', ['uq_band_taxes_band_id']],
    ]

    for table, foreignkeys in foreignkeys_to_drop:
        existing_foreignkeys = set(map(lambda x: x['name'], inspector.get_foreign_keys(table)))
        if is_sqlite:
            with op.batch_alter_table(table, reflect_kwargs=sqlite_reflect_kwargs) as batch_op:
                for foreignkey in foreignkeys:
                    if foreignkey in existing_foreignkeys:
                        batch_op.drop_constraint(foreignkey, type_='foreignkey')
        else:
            for foreignkey in foreignkeys:
                if foreignkey in existing_foreignkeys:
                    op.drop_constraint(foreignkey, table, type_='foreignkey')

    for table, primarykeys in primarykeys_to_drop:
        existing_primarykeys = set([inspector.get_pk_constraint(table)['name']])
        if is_sqlite:
            with op.batch_alter_table(table, reflect_kwargs=sqlite_reflect_kwargs) as batch_op:
                for primarykey in primarykeys:
                    if primarykey in existing_primarykeys:
                        batch_op.drop_constraint(primarykey, type_='primary')
        else:
            for primarykey in primarykeys:
                if primarykey in existing_primarykeys:
                    op.drop_constraint(primarykey, table, type_='primary')

    for table, uniqueconstraints in uniqueconstraints_to_drop:
        existing_uniqueconstraints = set(map(lambda x: x['name'], inspector.get_unique_constraints(table)))
        if is_sqlite:
            with op.batch_alter_table(table, reflect_kwargs=sqlite_reflect_kwargs) as batch_op:
                for uniqueconstraint in uniqueconstraints:
                    if uniqueconstraint in existing_uniqueconstraints:
                        batch_op.drop_constraint(uniqueconstraint, type_='unique')
        else:
            for uniqueconstraint in uniqueconstraints:
                if uniqueconstraint in existing_uniqueconstraints:
                    op.drop_constraint(uniqueconstraint, table, type_='unique')

    uniqueconstraints_to_add = [
        ['guest_bio', [('uq_guest_bio_guest_id', 'guest_id')]],
        ['guest_charity', [('uq_guest_charity_guest_id', 'guest_id')]],
        ['guest_info', [('uq_guest_info_guest_id', 'guest_id')]],
        ['guest_merch', [('uq_guest_merch_guest_id', 'guest_id')]],
        ['guest_panel', [('uq_guest_panel_guest_id', 'guest_id')]],
        ['guest_stage_plot', [('uq_guest_stage_plot_guest_id', 'guest_id')]],
        ['guest_taxes', [('uq_guest_taxes_guest_id', 'guest_id')]],
    ]

    primarykeys_to_add = [
        ['guest_group', [('pk_guest_group', 'id')]],
        ['guest_bio', [('pk_guest_bio', 'id')]],
        ['guest_charity', [('pk_guest_charity', 'id')]],
        ['guest_info', [('pk_guest_info', 'id')]],
        ['guest_merch', [('pk_guest_merch', 'id')]],
        ['guest_panel', [('pk_guest_panel', 'id')]],
        ['guest_stage_plot', [('pk_guest_stage_plot', 'id')]],
        ['guest_taxes', [('pk_guest_taxes', 'id')]],
    ]

    foreignkeys_to_add = [
        ['guest_group', [
            ('fk_guest_group_event_id_event', 'event', 'event_id', 'id'),
            ('fk_guest_group_group_id_group', 'group', 'group_id', 'id')]],
        ['guest_bio', [('fk_guest_bio_guest_id_guest_group', 'guest_group', 'guest_id', 'id')]],
        ['guest_charity', [('fk_guest_charity_guest_id_guest_group', 'guest_group', 'guest_id', 'id')]],
        ['guest_info', [('fk_guest_info_guest_id_guest_group', 'guest_group', 'guest_id', 'id')]],
        ['guest_merch', [('fk_guest_merch_guest_id_guest_group', 'guest_group', 'guest_id', 'id')]],
        ['guest_panel', [('fk_guest_panel_guest_id_guest_group', 'guest_group', 'guest_id', 'id')]],
        ['guest_stage_plot', [('fk_guest_stage_plot_guest_id_guest_group', 'guest_group', 'guest_id', 'id')]],
        ['guest_taxes', [('fk_guest_taxes_guest_id_guest_group', 'guest_group', 'guest_id', 'id')]],
        ['guest_autograph', [('fk_guest_autograph_guest_id_guest_group', 'guest_group', 'guest_id', 'id')]],
        ['guest_interview', [('fk_guest_interview_guest_id_guest_group', 'guest_group', 'guest_id', 'id')]],
        ['guest_travel_plans', [('fk_guest_travel_plans_guest_id_guest_group', 'guest_group', 'guest_id', 'id')]],
    ]

    for table, primarykeys in primarykeys_to_add:
        if is_sqlite:
            with op.batch_alter_table(table, reflect_kwargs=sqlite_reflect_kwargs) as batch_op:
                for primarykey, column in primarykeys:
                    batch_op.create_primary_key(op.f(primarykey), [column])
        else:
            for primarykey, column in primarykeys:
                op.create_primary_key(op.f(primarykey), table, [column])

    for table, uniqueconstraints in uniqueconstraints_to_add:
        if is_sqlite:
            with op.batch_alter_table(table, reflect_kwargs=sqlite_reflect_kwargs) as batch_op:
                for uniqueconstraint, column in uniqueconstraints:
                    batch_op.create_unique_constraint(op.f(uniqueconstraint), [column])
        else:
            for uniqueconstraint, column in uniqueconstraints:
                op.create_unique_constraint(op.f(uniqueconstraint), table, [column])

    for table, foreignkeys in foreignkeys_to_add:
        if is_sqlite:
            with op.batch_alter_table(table, reflect_kwargs=sqlite_reflect_kwargs) as batch_op:
                for foreignkey, remote_table, column, remote_column in foreignkeys:
                    batch_op.create_foreign_key(op.f(foreignkey), remote_table, [column], [remote_column])
        else:
            for foreignkey, remote_table, column, remote_column in foreignkeys:
                op.create_foreign_key(op.f(foreignkey), table, remote_table, [column], [remote_column])

    if is_sqlite:
        with op.batch_alter_table('guest_merch', reflect_kwargs=sqlite_reflect_kwargs) as batch_op:
            batch_op.add_column(sa.Column('bringing_boxes', sa.Unicode(), server_default='', nullable=False))
            batch_op.add_column(sa.Column('extra_info', sa.Unicode(), server_default='', nullable=False))
            batch_op.add_column(sa.Column('inventory', MutableDict.as_mutable(JSON), server_default='{}', nullable=False))
            batch_op.add_column(sa.Column('handlers', MutableDict.as_mutable(JSON), server_default='[]', nullable=False))
            batch_op.add_column(sa.Column('poc_email', sa.Unicode(), server_default='', nullable=False))
            batch_op.add_column(sa.Column('poc_first_name', sa.Unicode(), server_default='', nullable=False))
            batch_op.add_column(sa.Column('poc_last_name', sa.Unicode(), server_default='', nullable=False))
            batch_op.add_column(sa.Column('poc_phone', sa.Unicode(), server_default='', nullable=False))
            batch_op.add_column(sa.Column('poc_zip_code', sa.Unicode(), server_default='', nullable=False))
            batch_op.add_column(sa.Column('poc_address1', sa.Unicode(), server_default='', nullable=False))
            batch_op.add_column(sa.Column('poc_address2', sa.Unicode(), server_default='', nullable=False))
            batch_op.add_column(sa.Column('poc_city', sa.Unicode(), server_default='', nullable=False))
            batch_op.add_column(sa.Column('poc_region', sa.Unicode(), server_default='', nullable=False))
            batch_op.add_column(sa.Column('poc_country', sa.Unicode(), server_default='', nullable=False))
            batch_op.add_column(sa.Column('poc_is_group_leader', sa.Boolean(), server_default='False', nullable=False))
    else:
        op.add_column('guest_merch', sa.Column('bringing_boxes', sa.Unicode(), server_default='', nullable=False))
        op.add_column('guest_merch', sa.Column('extra_info', sa.Unicode(), server_default='', nullable=False))
        op.add_column('guest_merch', sa.Column('inventory', MutableDict.as_mutable(JSON), server_default='{}', nullable=False))
        op.add_column('guest_merch', sa.Column('handlers', MutableDict.as_mutable(JSON), server_default='[]', nullable=False))
        op.add_column('guest_merch', sa.Column('poc_email', sa.Unicode(), server_default='', nullable=False))
        op.add_column('guest_merch', sa.Column('poc_first_name', sa.Unicode(), server_default='', nullable=False))
        op.add_column('guest_merch', sa.Column('poc_last_name', sa.Unicode(), server_default='', nullable=False))
        op.add_column('guest_merch', sa.Column('poc_phone', sa.Unicode(), server_default='', nullable=False))
        op.add_column('guest_merch', sa.Column('poc_zip_code', sa.Unicode(), server_default='', nullable=False))
        op.add_column('guest_merch', sa.Column('poc_address1', sa.Unicode(), server_default='', nullable=False))
        op.add_column('guest_merch', sa.Column('poc_address2', sa.Unicode(), server_default='', nullable=False))
        op.add_column('guest_merch', sa.Column('poc_city', sa.Unicode(), server_default='', nullable=False))
        op.add_column('guest_merch', sa.Column('poc_region', sa.Unicode(), server_default='', nullable=False))
        op.add_column('guest_merch', sa.Column('poc_country', sa.Unicode(), server_default='', nullable=False))
        op.add_column('guest_merch', sa.Column('poc_is_group_leader', sa.Boolean(), server_default='False', nullable=False))


def downgrade():
    op.create_unique_constraint('uq_band_taxes_band_id', 'guest_taxes', ['guest_id'])
    op.drop_constraint(op.f('uq_guest_taxes_guest_id'), 'guest_taxes', type_='unique')
    op.create_unique_constraint('uq_band_stage_plot_band_id', 'guest_stage_plot', ['guest_id'])
    op.drop_constraint(op.f('uq_guest_stage_plot_guest_id'), 'guest_stage_plot', type_='unique')
    op.create_unique_constraint('uq_band_panel_band_id', 'guest_panel', ['guest_id'])
    op.drop_constraint(op.f('uq_guest_panel_guest_id'), 'guest_panel', type_='unique')
    op.create_unique_constraint('uq_band_merch_band_id', 'guest_merch', ['guest_id'])
    op.drop_constraint(op.f('uq_guest_merch_guest_id'), 'guest_merch', type_='unique')
    op.create_unique_constraint('uq_band_info_band_id', 'guest_info', ['guest_id'])
    op.drop_constraint(op.f('uq_guest_info_guest_id'), 'guest_info', type_='unique')
    op.create_unique_constraint('uq_band_charity_band_id', 'guest_charity', ['guest_id'])
    op.drop_constraint(op.f('uq_guest_charity_guest_id'), 'guest_charity', type_='unique')
    op.create_unique_constraint('uq_band_bio_band_id', 'guest_bio', ['guest_id'])
    op.drop_constraint(op.f('uq_guest_bio_guest_id'), 'guest_bio', type_='unique')

    op.drop_column('guest_merch', 'poc_is_group_leader')
    op.drop_column('guest_merch', 'poc_country')
    op.drop_column('guest_merch', 'poc_region')
    op.drop_column('guest_merch', 'poc_city')
    op.drop_column('guest_merch', 'poc_address2')
    op.drop_column('guest_merch', 'poc_address1')
    op.drop_column('guest_merch', 'poc_zip_code')
    op.drop_column('guest_merch', 'poc_phone')
    op.drop_column('guest_merch', 'poc_last_name')
    op.drop_column('guest_merch', 'poc_first_name')
    op.drop_column('guest_merch', 'poc_email')
    op.drop_column('guest_merch', 'handlers')
    op.drop_column('guest_merch', 'inventory')
    op.drop_column('guest_merch', 'extra_info')
    op.drop_column('guest_merch', 'bringing_boxes')
