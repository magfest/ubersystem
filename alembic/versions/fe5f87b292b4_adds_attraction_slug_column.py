"""Adds attraction slug column

Revision ID: fe5f87b292b4
Revises: 1c87fd8da02e
Create Date: 2017-12-17 02:01:36.942202

"""


# revision identifiers, used by Alembic.
revision = 'fe5f87b292b4'
down_revision = '1c87fd8da02e'
branch_labels = None
depends_on = None

import re
from alembic import op
import sqlalchemy as sa
import residue
from sqlalchemy.sql import table
from pockets import sluggify


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


attraction_table = table(
    'attraction',
    sa.Column('id', residue.UUID()),
    sa.Column('name', sa.Unicode()),
    sa.Column('slug', sa.Boolean()),
)


attraction_feature_table = table(
    'attraction_feature',
    sa.Column('id', residue.UUID()),
    sa.Column('name', sa.Unicode()),
    sa.Column('slug', sa.Boolean()),
)


def upgrade():
    if is_sqlite:
        with op.batch_alter_table('attraction', reflect_kwargs=sqlite_reflect_kwargs) as batch_op:
            batch_op.add_column(sa.Column('slug', sa.Unicode(), server_default='', nullable=False))
        with op.batch_alter_table('attraction_feature', reflect_kwargs=sqlite_reflect_kwargs) as batch_op:
            batch_op.add_column(sa.Column('slug', sa.Unicode(), server_default='', nullable=False))
    else:
        op.add_column('attraction', sa.Column('slug', sa.Unicode(), server_default='', nullable=False))
        op.add_column('attraction_feature', sa.Column('slug', sa.Unicode(), server_default='', nullable=False))

    connection = op.get_bind()
    for attraction in connection.execute(attraction_table.select()):
        connection.execute(
            attraction_table.update().where(
                attraction_table.c.id == attraction.id
            ).values(
                slug=sluggify(attraction.name)
            )
        )

    for feature in connection.execute(attraction_feature_table.select()):
        connection.execute(
            attraction_feature_table.update().where(
                attraction_feature_table.c.id == feature.id
            ).values(
                slug=sluggify(feature.name)
            )
        )

    if is_sqlite:
        with op.batch_alter_table('attraction', reflect_kwargs=sqlite_reflect_kwargs) as batch_op:
            batch_op.create_unique_constraint(op.f('uq_attraction_slug'), ['slug'])
        with op.batch_alter_table('attraction_feature', reflect_kwargs=sqlite_reflect_kwargs) as batch_op:
            batch_op.create_unique_constraint(op.f('uq_attraction_feature_slug'), ['slug', 'attraction_id'])
    else:
        op.create_unique_constraint(op.f('uq_attraction_slug'), 'attraction', ['slug'])
        op.create_unique_constraint(op.f('uq_attraction_feature_slug'), 'attraction_feature', ['slug', 'attraction_id'])


def downgrade():
    op.drop_constraint(op.f('uq_attraction_slug'), 'attraction', type_='unique')
    op.drop_column('attraction', 'slug')
    op.drop_constraint(op.f('uq_attraction_feature_slug'), 'attraction_feature', type_='unique')
    op.drop_column('attraction_feature', 'slug')
