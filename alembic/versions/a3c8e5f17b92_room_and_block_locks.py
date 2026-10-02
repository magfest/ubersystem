"""Room locks and a per-room export stamp

Adds room_assignment.locked (admin lock) and room_assignment.exported_at
(when a hotel export first included the row). exported_at is backfilled
from the export log: the earliest booking export after the row was
created and, for inactive rows, before their last change. Rows on an
entry with the Passkey export flag count as exported.

Revision ID: a3c8e5f17b92
Revises: f7c3d9e1a2b4
Create Date: 2026-09-23 12:00:00.000000
"""


# revision identifiers, used by Alembic.
revision = 'a3c8e5f17b92'
down_revision = 'f7c3d9e1a2b4'
branch_labels = None
depends_on = None

import sqlalchemy as sa
from alembic import op

from uber.config import c


def upgrade():
    op.add_column('room_assignment', sa.Column('locked', sa.Boolean(), server_default='false', nullable=False))
    op.add_column('room_assignment', sa.Column('exported_at', sa.DateTime(timezone=True), nullable=True))

    live = ', '.join(str(int(s)) for s in c.HOTEL_LIVE_ASSIGNMENT_STATUSES)
    op.execute(sa.text(f"""
        UPDATE room_assignment ra
        SET exported_at = (
            SELECT min(log.exported_at)
            FROM hotel_export_log log
            JOIN hotel_room_inventory inv ON inv.hotel_id = log.hotel_id
            WHERE inv.id = ra.inventory_id
              AND log.export_type = 'room_export'
              AND log.exported_at >= ra.created
              AND (ra.status IN ({live})
                   OR log.exported_at < coalesce(ra.last_modified_at, ra.last_updated)))
        WHERE ra.exported_at IS NULL
    """))
    op.execute(sa.text("""
        UPDATE room_assignment ra
        SET exported_at = now()
        FROM lottery_application app
        WHERE app.id = ra.lottery_application_id
          AND app.export_locked
          AND ra.exported_at IS NULL
    """))


def downgrade():
    op.drop_column('room_assignment', 'exported_at')
    op.drop_column('room_assignment', 'locked')
