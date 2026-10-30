"""Migrate costs and overridden prices from dollars to cents

Revision ID: c8d3e1f7a2b9
Revises: 3c9e2a7f41d8
Create Date: 2026-10-30 00:00:00.000000

"""

# revision identifiers, used by Alembic.
revision = 'c8d3e1f7a2b9'
down_revision = '3c9e2a7f41d8'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.execute(
        sa.text(
            'UPDATE attendee SET badge_cost = badge_cost * 100 WHERE badge_cost IS NOT NULL'
        )
    )
    op.execute(
        sa.text(
            'UPDATE attendee SET default_cost = default_cost * 100 WHERE default_cost IS NOT NULL'
        )
    )
    op.execute(
        sa.text(
            'UPDATE attendee SET overridden_price = overridden_price * 100 WHERE overridden_price IS NOT NULL'
        )
    )
    op.execute(sa.text('UPDATE "group" SET cost = cost * 100 WHERE cost IS NOT NULL'))
    op.execute(
        sa.text(
            'UPDATE art_show_application SET default_cost = default_cost * 100 WHERE default_cost IS NOT NULL'
        )
    )
    op.execute(
        sa.text(
            'UPDATE art_show_application SET overridden_price = overridden_price * 100 WHERE overridden_price IS NOT NULL'
        )
    )
    op.execute(
        sa.text(
            'UPDATE artist_marketplace_application SET overridden_price = overridden_price * 100 WHERE overridden_price IS NOT NULL'
        )
    )


def downgrade():
    op.execute(
        sa.text(
            'UPDATE attendee SET badge_cost = badge_cost / 100 WHERE badge_cost IS NOT NULL'
        )
    )
    op.execute(
        sa.text(
            'UPDATE attendee SET default_cost = default_cost / 100 WHERE default_cost IS NOT NULL'
        )
    )
    op.execute(
        sa.text(
            'UPDATE attendee SET overridden_price = overridden_price / 100 WHERE overridden_price IS NOT NULL'
        )
    )
    op.execute(sa.text('UPDATE "group" SET cost = cost / 100 WHERE cost IS NOT NULL'))
    op.execute(
        sa.text(
            'UPDATE art_show_application SET default_cost = default_cost / 100 WHERE default_cost IS NOT NULL'
        )
    )
    op.execute(
        sa.text(
            'UPDATE art_show_application SET overridden_price = overridden_price / 100 WHERE overridden_price IS NOT NULL'
        )
    )
    op.execute(
        sa.text(
            'UPDATE artist_marketplace_application SET overridden_price = overridden_price / 100 WHERE overridden_price IS NOT NULL'
        )
    )
