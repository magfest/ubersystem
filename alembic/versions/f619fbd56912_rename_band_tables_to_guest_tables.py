"""Rename band tables to guest tables

Revision ID: f619fbd56912
Revises: 5dced3c6ef91
Create Date: 2017-09-18 07:45:24.077355

"""


# revision identifiers, used by Alembic.
revision = 'f619fbd56912'
down_revision = '5dced3c6ef91'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
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
    op.rename_table('band', 'guest_group')

    op.rename_table('band_bio', 'guest_bio')
    if is_sqlite:
        with op.batch_alter_table('guest_bio', reflect_kwargs=sqlite_reflect_kwargs) as batch_op:
            batch_op.alter_column('band_id', new_column_name='guest_id')
    else:
        op.alter_column('guest_bio', 'band_id', new_column_name='guest_id')

    op.rename_table('band_charity', 'guest_charity')
    if is_sqlite:
        with op.batch_alter_table('guest_charity', reflect_kwargs=sqlite_reflect_kwargs) as batch_op:
            batch_op.alter_column('band_id', new_column_name='guest_id')
    else:
        op.alter_column('guest_charity', 'band_id', new_column_name='guest_id')

    op.rename_table('band_info', 'guest_info')
    if is_sqlite:
        with op.batch_alter_table('guest_info', reflect_kwargs=sqlite_reflect_kwargs) as batch_op:
            batch_op.alter_column('band_id', new_column_name='guest_id')
    else:
        op.alter_column('guest_info', 'band_id', new_column_name='guest_id')

    op.rename_table('band_merch', 'guest_merch')
    if is_sqlite:
        with op.batch_alter_table('guest_merch', reflect_kwargs=sqlite_reflect_kwargs) as batch_op:
            batch_op.alter_column('band_id', new_column_name='guest_id')
    else:
        op.alter_column('guest_merch', 'band_id', new_column_name='guest_id')

    op.rename_table('band_panel', 'guest_panel')
    if is_sqlite:
        with op.batch_alter_table('guest_panel', reflect_kwargs=sqlite_reflect_kwargs) as batch_op:
            batch_op.alter_column('band_id', new_column_name='guest_id')
    else:
        op.alter_column('guest_panel', 'band_id', new_column_name='guest_id')

    op.rename_table('band_stage_plot', 'guest_stage_plot')
    if is_sqlite:
        with op.batch_alter_table('guest_stage_plot', reflect_kwargs=sqlite_reflect_kwargs) as batch_op:
            batch_op.alter_column('band_id', new_column_name='guest_id')
    else:
        op.alter_column('guest_stage_plot', 'band_id', new_column_name='guest_id')

    op.rename_table('band_taxes', 'guest_taxes')
    if is_sqlite:
        with op.batch_alter_table('guest_taxes', reflect_kwargs=sqlite_reflect_kwargs) as batch_op:
            batch_op.alter_column('band_id', new_column_name='guest_id')
    else:
        op.alter_column('guest_taxes', 'band_id', new_column_name='guest_id')


def downgrade():
    op.rename_table('guest_group', 'band')

    op.rename_table('guest_bio', 'band_bio')
    op.alter_column('band_bio', 'guest_id', new_column_name='band_id')

    op.rename_table('guest_charity', 'band_charity')
    op.alter_column('band_charity', 'guest_id', new_column_name='band_id')

    op.rename_table('guest_info', 'band_info')
    op.alter_column('band_info', 'guest_id', new_column_name='band_id')

    op.rename_table('guest_merch', 'band_merch')
    op.alter_column('band_merch', 'guest_id', new_column_name='band_id')

    op.rename_table('guest_panel', 'band_panel')
    op.alter_column('band_panel', 'guest_id', new_column_name='band_id')

    op.rename_table('guest_stage_plot', 'band_stage_plot')
    op.alter_column('band_stage_plot', 'guest_id', new_column_name='band_id')

    op.rename_table('guest_taxes', 'band_taxes')
    op.alter_column('band_taxes', 'guest_id', new_column_name='band_id')
