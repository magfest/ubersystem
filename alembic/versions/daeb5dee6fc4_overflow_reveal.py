"""Rename waitlist_reveal to overflow_reveal and hold several booking links

Revision ID: daeb5dee6fc4
Revises: f7c3d9e1a2b4
Create Date: 2026-10-06 12:00:00.000000
"""


# revision identifiers, used by Alembic.
revision = 'daeb5dee6fc4'
down_revision = 'f7c3d9e1a2b4'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# (table after rename, old name, new name). Postgres NOT NULL constraint names
# are left alone; nothing references them.
CONSTRAINTS = [
    ('overflow_reveal', 'pk_waitlist_reveal', 'pk_overflow_reveal'),
    ('overflow_reveal_link', 'pk_waitlist_reveal_link', 'pk_overflow_reveal_link'),
    ('overflow_reveal_link', 'fk_waitlist_reveal_link_attendee_id_attendee',
     'fk_overflow_reveal_link_attendee_id_attendee'),
    ('overflow_reveal_link', 'fk_waitlist_reveal_link_waitlist_reveal_id_waitlist_reveal',
     'fk_overflow_reveal_link_overflow_reveal_id_overflow_reveal'),
    ('overflow_reveal_link', 'uq_waitlist_reveal_attendee', 'uq_overflow_reveal_attendee'),
    ('overflow_reveal_link', 'uq_waitlist_reveal_link_token', 'uq_overflow_reveal_link_token'),
]

INDEXES = [
    ('uq_waitlist_reveal_shared_token', 'uq_overflow_reveal_shared_token'),
    ('ix_waitlist_reveal_link_attendee_id', 'ix_overflow_reveal_link_attendee_id'),
    ('ix_waitlist_reveal_link_waitlist_reveal_id', 'ix_overflow_reveal_link_overflow_reveal_id'),
]

OLD_IDENT = 'hotel_lottery_waitlist_reveal'
NEW_IDENT = 'hotel_lottery_overflow_reveal'


def _rename_ident(old, new):
    # Renamed in place so the AutomatedEmail row keeps its id and settings;
    # reconcile_fixtures leaves orphaned idents behind rather than removing them.
    op.execute(sa.text("UPDATE automated_email SET ident = :new WHERE ident = :old")
               .bindparams(old=old, new=new))
    op.execute(sa.text("UPDATE email SET ident = :new WHERE ident = :old")
               .bindparams(old=old, new=new))


def upgrade():
    op.add_column('waitlist_reveal', sa.Column(
        'booking_links', postgresql.JSONB(astext_type=sa.Text()),
        server_default='[]', nullable=False))
    op.execute("""
        UPDATE waitlist_reveal
        SET booking_links = jsonb_build_array(
            jsonb_build_object('label', '', 'url', external_url))
        WHERE external_url <> ''
    """)
    op.drop_column('waitlist_reveal', 'external_url')

    op.rename_table('waitlist_reveal', 'overflow_reveal')
    op.rename_table('waitlist_reveal_link', 'overflow_reveal_link')
    op.alter_column('overflow_reveal_link', 'waitlist_reveal_id',
                    new_column_name='overflow_reveal_id')
    for table, old, new in CONSTRAINTS:
        op.execute(f'ALTER TABLE {table} RENAME CONSTRAINT {old} TO {new}')
    for old, new in INDEXES:
        op.execute(f'ALTER INDEX {old} RENAME TO {new}')
    _rename_ident(OLD_IDENT, NEW_IDENT)


def downgrade():
    _rename_ident(NEW_IDENT, OLD_IDENT)
    for old, new in INDEXES:
        op.execute(f'ALTER INDEX {new} RENAME TO {old}')
    for table, old, new in CONSTRAINTS:
        op.execute(f'ALTER TABLE {table} RENAME CONSTRAINT {new} TO {old}')
    op.alter_column('overflow_reveal_link', 'overflow_reveal_id',
                    new_column_name='waitlist_reveal_id')
    op.rename_table('overflow_reveal_link', 'waitlist_reveal_link')
    op.rename_table('overflow_reveal', 'waitlist_reveal')

    op.add_column('waitlist_reveal', sa.Column(
        'external_url', sa.Unicode(), server_default='', nullable=False))
    # Only the first link survives; external_url held one URL.
    op.execute("""
        UPDATE waitlist_reveal
        SET external_url = COALESCE(booking_links->0->>'url', '')
    """)
    op.drop_column('waitlist_reveal', 'booking_links')
