"""Adds fields to panel_application

Revision ID: 3733faf640e9
Revises: 9359297269a8
Create Date: 2017-07-25 08:43:56.445034

"""


# revision identifiers, used by Alembic.
revision = '3733faf640e9'
down_revision = '9359297269a8'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import table
import residue
from uber.config import c

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

panel_app_helper = table(
        'panel_application',
        sa.Column('id', residue.UUID(), nullable=False),
        sa.Column('length', sa.Unicode()),
        sa.Column('length_text', sa.Unicode()),
        sa.Column('length_reason', sa.Unicode())
        # Other columns not needed
    )

def upgrade():
    if is_sqlite:
        with op.batch_alter_table('panel_application', reflect_kwargs=sqlite_reflect_kwargs) as batch_op:
            batch_op.add_column(sa.Column('cost_desc', sa.Unicode(), server_default='', nullable=False))
            batch_op.add_column(sa.Column('extra_info', sa.Unicode(), server_default='', nullable=False))
            batch_op.add_column(sa.Column('has_cost', sa.Boolean(), server_default='False', nullable=False))
            batch_op.add_column(sa.Column('length_reason', sa.Unicode(), server_default='', nullable=False))
            batch_op.add_column(sa.Column('length_text', sa.Unicode(), server_default='', nullable=False))
            batch_op.add_column(sa.Column('livestream', sa.Integer(), server_default=str(c.OPT_IN), nullable=False))
            batch_op.add_column(sa.Column('need_tables', sa.Boolean(), server_default='False', nullable=False))
            batch_op.add_column(sa.Column('tables_desc', sa.Unicode(), server_default='', nullable=False))

            # We don't really care about preserving data during SQLite upgrades
            batch_op.drop_column('length')
            batch_op.add_column(sa.Column('length', sa.Integer(), server_default=str(c.SIXTY_MIN), nullable=False))
    else:
        op.add_column('panel_application', sa.Column('cost_desc', sa.Unicode(), server_default='', nullable=False))
        op.add_column('panel_application', sa.Column('extra_info', sa.Unicode(), server_default='', nullable=False))
        op.add_column('panel_application', sa.Column('has_cost', sa.Boolean(), server_default='False', nullable=False))
        op.add_column('panel_application', sa.Column('length_reason', sa.Unicode(), server_default='', nullable=False))
        op.add_column('panel_application', sa.Column('length_text', sa.Unicode(), server_default='', nullable=False))
        op.add_column('panel_application', sa.Column('livestream', sa.Integer(), server_default=str(c.OPT_IN), nullable=False))
        op.add_column('panel_application', sa.Column('need_tables', sa.Boolean(), server_default='False', nullable=False))
        op.add_column('panel_application', sa.Column('tables_desc', sa.Unicode(), server_default='', nullable=False))

        # In order to preserve data during the upgrade, we copy 'length' into 'length_text'
        connection = op.get_bind()

        for panel_app in connection.execute(panel_app_helper.select()):
            new_length_text = panel_app.length
            connection.execute(
                panel_app_helper.update().where(
                    panel_app_helper.c.id == panel_app.id
                ).values(
                    length_text=new_length_text,
                    length=c.OTHER,
                    length_reason="Automated data migration."
                )
            )

        # Converting from string to integer normally requires raw SQL
        # Let's just drop and re-add the column since we moved the data
        op.drop_column('panel_application', 'length')
        op.add_column('panel_application', sa.Column('length', sa.Integer(), server_default=str(c.SIXTY_MIN), nullable=False))



def downgrade():
    op.alter_column('panel_application', 'length', type_=sa.Unicode(), server_default='', nullable=False)
    op.drop_column('panel_application', 'tables_desc')
    op.drop_column('panel_application', 'need_tables')
    op.drop_column('panel_application', 'livestream')
    op.drop_column('panel_application', 'length_text')
    op.drop_column('panel_application', 'length_reason')
    op.drop_column('panel_application', 'has_cost')
    op.drop_column('panel_application', 'extra_info')
    op.drop_column('panel_application', 'cost_desc')
