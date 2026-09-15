"""Record which applications each lottery run considered

Revision ID: b7c3d9e41f02
Revises: 9ee2f61777d4, e1bdc27ce73c
Create Date: 2026-09-16 10:00:00.000000

Merges the two hotel-lottery heads and adds LotteryRun.considered_application_ids,
the snapshot of non-group entries a run considered, so the run detail page can
compare award statistics against the pool the solver drew from.
"""


# revision identifiers, used by Alembic.
revision = 'b7c3d9e41f02'
down_revision = ('9ee2f61777d4', 'e1bdc27ce73c')
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


def upgrade():
    op.add_column('lottery_run', sa.Column(
        'considered_application_ids', postgresql.JSONB(astext_type=sa.Text()),
        server_default='[]', nullable=False))


def downgrade():
    op.drop_column('lottery_run', 'considered_application_ids')
