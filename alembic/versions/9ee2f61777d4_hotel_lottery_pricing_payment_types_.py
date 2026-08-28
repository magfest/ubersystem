"""Hotel lottery pricing, payment types, imports, and permissions

Numeric per-night and per-occupancy room pricing, an extensible payment type
replacing the require_cc boolean, partition bill references and room-number
permissions, independent staff eligibilities, waitlist reveal link options,
and the room-list import mapping templates.

The price backfill is lossy in the downgrade direction: legacy price strings
that carried text beyond a number were merged into pricing_notes on the way
up and are not split back out on the way down. The partition_audit_log
downgrade deletes rows detached from their partition, since the column
returns to NOT NULL.

Revision ID: 9ee2f61777d4
Revises: 1331e94c332e
Create Date: 2026-08-28 09:14:22.108431

"""


# revision identifiers, used by Alembic.
revision = '9ee2f61777d4'
down_revision = '1331e94c332e'
branch_labels = None
depends_on = None

from alembic import op
from sqlalchemy.dialects import postgresql
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

# A number, optionally preceded by a currency symbol, occupying the whole
# value. Anything else is kept verbatim in pricing_notes as well.
BARE_PRICE = r'^\s*\$?\s*[0-9]+(\.[0-9]+)?\s*$'
# The outer group is required: substring(x from pattern) returns the first
# capture group when there is one, so an inner-only group yields the decimals.
LEADING_NUMBER = r'([0-9]+(?:\.[0-9]+)?)'


def upgrade():
    op.create_table(
        'import_mapping_template',
        sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
        sa.Column('created', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_updated', sa.DateTime(timezone=True), nullable=False),
        sa.Column('external_id', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
        sa.Column('last_synced', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
        sa.Column('name', sa.Unicode(), server_default='', nullable=False),
        sa.Column('description', sa.Unicode(), server_default='', nullable=False),
        sa.Column('source_signature', sa.Unicode(), server_default='', nullable=False),
        sa.Column('sheet_name', sa.Unicode(), server_default='', nullable=False),
        sa.Column('header_row', sa.Integer(), server_default='1', nullable=False),
        sa.Column('active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('column_map', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
        sa.Column('enum_map', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
        sa.Column('format_map', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_import_mapping_template')))

    op.create_table(
        'inventory_price',
        sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
        sa.Column('created', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_updated', sa.DateTime(timezone=True), nullable=False),
        sa.Column('external_id', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
        sa.Column('last_synced', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
        sa.Column('inventory_id', sa.Uuid(as_uuid=False), nullable=False),
        sa.Column('night_date', sa.Date(), nullable=True),
        sa.Column('occupancy', sa.Integer(), nullable=True),
        sa.Column('is_staff', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('price', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.ForeignKeyConstraint(['inventory_id'], ['hotel_room_inventory.id'],
                                name=op.f('fk_inventory_price_inventory_id_hotel_room_inventory'),
                                ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_inventory_price')),
        # NULL means "applies to any night / any occupancy", so NULLs must
        # collide rather than being treated as distinct values.
        sa.UniqueConstraint('inventory_id', 'is_staff', 'night_date', 'occupancy',
                            name='uq_inventory_price_scope',
                            postgresql_nulls_not_distinct=True))
    op.create_index(op.f('ix_inventory_price_inventory_id'), 'inventory_price', ['inventory_id'])

    # Staff eligibility. Defaults true so every existing staffer keeps the
    # lottery access they have today; hotel_eligible stays the shared-room flag.
    op.add_column('attendee', sa.Column('staff_lottery_eligible', sa.Boolean(),
                                        server_default='true', nullable=False))

    # Payment types. require_cc becomes a property derived from this column.
    op.add_column('room_assignment', sa.Column('payment_type', sa.Unicode(),
                                               server_default='credit_card', nullable=False))
    op.execute("""
        UPDATE room_assignment
        SET payment_type = CASE WHEN require_cc THEN 'credit_card' ELSE 'masterbill' END
    """)
    op.drop_column('room_assignment', 'require_cc')

    # Numeric pricing. New column names rather than an in-place type change so
    # any reader still expecting the old strings fails loudly.
    op.add_column('hotel_room_inventory', sa.Column('base_price', sa.Numeric(precision=10, scale=2),
                                                    nullable=True))
    op.add_column('hotel_room_inventory', sa.Column('base_staff_price', sa.Numeric(precision=10, scale=2),
                                                    nullable=True))
    op.add_column('hotel_room_inventory', sa.Column('price_per_night', sa.Boolean(),
                                                    server_default='false', nullable=False))
    op.add_column('hotel_room_inventory', sa.Column('price_per_occupancy', sa.Boolean(),
                                                    server_default='false', nullable=False))
    op.add_column('hotel_room_inventory', sa.Column('pricing_notes', sa.Unicode(),
                                                    server_default='', nullable=False))

    for old_col, new_col, label in (('price', 'base_price', 'Legacy price'),
                                    ('staff_price', 'base_staff_price', 'Legacy staff price')):
        op.execute(f"""
            UPDATE hotel_room_inventory
            SET {new_col} = (substring({old_col} from '{LEADING_NUMBER}'))::numeric
            WHERE {old_col} <> '' AND substring({old_col} from '{LEADING_NUMBER}') IS NOT NULL
        """)
        # Keep anything we could not read as a bare number, so no admin-entered
        # text is lost to the conversion.
        op.execute(f"""
            UPDATE hotel_room_inventory
            SET pricing_notes = trim(both E'\n' from pricing_notes || E'\n' || '{label}: ' || {old_col})
            WHERE {old_col} <> '' AND {old_col} !~ '{BARE_PRICE}'
        """)

    op.drop_column('hotel_room_inventory', 'price')
    op.drop_column('hotel_room_inventory', 'staff_price')

    op.add_column('inventory_partition', sa.Column('bill_reference', sa.Unicode(),
                                                   server_default='', nullable=False))

    op.add_column('partition_owner', sa.Column('can_view_room_numbers', sa.Boolean(),
                                               server_default='false', nullable=False))
    op.add_column('partition_owner', sa.Column('can_edit_room_numbers', sa.Boolean(),
                                               server_default='false', nullable=False))

    # Detach audit entries instead of cascading them away, so deleting a
    # partition no longer destroys the record of what was done inside it.
    op.add_column('partition_audit_log', sa.Column('partition_name', sa.Unicode(),
                                                   server_default='', nullable=False))
    op.alter_column('partition_audit_log', 'partition_id', existing_type=sa.Uuid(as_uuid=False),
                    nullable=True)
    op.drop_constraint(op.f('fk_partition_audit_log_partition_id_inventory_partition'),
                       'partition_audit_log', type_='foreignkey')
    op.create_foreign_key(op.f('fk_partition_audit_log_partition_id_inventory_partition'),
                          'partition_audit_log', 'inventory_partition', ['partition_id'], ['id'],
                          ondelete='SET NULL')

    op.add_column('waitlist_reveal', sa.Column('use_unique_links', sa.Boolean(),
                                               server_default='true', nullable=False))
    op.add_column('waitlist_reveal', sa.Column('shared_token', sa.Unicode(),
                                               server_default='', nullable=False))
    op.add_column('waitlist_reveal', sa.Column('shared_clicks', sa.Integer(),
                                               server_default='0', nullable=False))
    op.add_column('waitlist_reveal', sa.Column('require_login', sa.Boolean(),
                                               server_default='false', nullable=False))
    op.create_index('uq_waitlist_reveal_shared_token', 'waitlist_reveal', ['shared_token'],
                    unique=True, postgresql_where=sa.text("shared_token <> ''"))

    # Room-list imports.
    op.add_column('lottery_hotel', sa.Column('default_import_template_id', sa.Uuid(as_uuid=False),
                                             nullable=True))
    op.create_foreign_key(op.f('fk_lottery_hotel_default_import_template_id_import_mapping_template'),
                          'lottery_hotel', 'import_mapping_template',
                          ['default_import_template_id'], ['id'], ondelete='SET NULL')

    op.add_column('hotel_import_file', sa.Column('status', sa.Unicode(),
                                                 server_default='', nullable=False))
    op.add_column('hotel_import_file', sa.Column('processed_at', sa.DateTime(timezone=True),
                                                 nullable=True))
    op.add_column('hotel_import_file', sa.Column('processed_by', sa.Unicode(),
                                                 server_default='', nullable=False))
    op.add_column('hotel_import_file', sa.Column('template_id', sa.Uuid(as_uuid=False),
                                                 nullable=True))
    op.add_column('hotel_import_file', sa.Column('parsed_rows', postgresql.JSONB(astext_type=sa.Text()),
                                                 server_default='[]', nullable=False))
    op.add_column('hotel_import_file', sa.Column('parse_error', sa.Unicode(),
                                                 server_default='', nullable=False))
    op.add_column('hotel_import_file', sa.Column('matched_count', sa.Integer(),
                                                 server_default='0', nullable=False))
    op.add_column('hotel_import_file', sa.Column('ambiguous_count', sa.Integer(),
                                                 server_default='0', nullable=False))
    op.add_column('hotel_import_file', sa.Column('unmatched_count', sa.Integer(),
                                                 server_default='0', nullable=False))
    op.create_foreign_key(op.f('fk_hotel_import_file_template_id_import_mapping_template'),
                          'hotel_import_file', 'import_mapping_template', ['template_id'], ['id'],
                          ondelete='SET NULL')
    op.create_index(op.f('ix_hotel_import_file_status'), 'hotel_import_file', ['status'])


def downgrade():
    op.drop_index(op.f('ix_hotel_import_file_status'), table_name='hotel_import_file')
    op.drop_constraint(op.f('fk_hotel_import_file_template_id_import_mapping_template'),
                       'hotel_import_file', type_='foreignkey')
    for col in ('unmatched_count', 'ambiguous_count', 'matched_count', 'parse_error',
                'parsed_rows', 'template_id', 'processed_by', 'processed_at', 'status'):
        op.drop_column('hotel_import_file', col)

    op.drop_constraint(op.f('fk_lottery_hotel_default_import_template_id_import_mapping_template'),
                       'lottery_hotel', type_='foreignkey')
    op.drop_column('lottery_hotel', 'default_import_template_id')

    op.drop_index('uq_waitlist_reveal_shared_token', table_name='waitlist_reveal')
    for col in ('require_login', 'shared_clicks', 'shared_token', 'use_unique_links'):
        op.drop_column('waitlist_reveal', col)

    # partition_id returns to NOT NULL, so entries whose partition is gone
    # cannot be kept.
    op.execute("DELETE FROM partition_audit_log WHERE partition_id IS NULL")
    op.drop_constraint(op.f('fk_partition_audit_log_partition_id_inventory_partition'),
                       'partition_audit_log', type_='foreignkey')
    op.create_foreign_key(op.f('fk_partition_audit_log_partition_id_inventory_partition'),
                          'partition_audit_log', 'inventory_partition', ['partition_id'], ['id'],
                          ondelete='CASCADE')
    op.alter_column('partition_audit_log', 'partition_id', existing_type=sa.Uuid(as_uuid=False),
                    nullable=False)
    op.drop_column('partition_audit_log', 'partition_name')

    op.drop_column('partition_owner', 'can_edit_room_numbers')
    op.drop_column('partition_owner', 'can_view_room_numbers')
    op.drop_column('inventory_partition', 'bill_reference')

    op.add_column('hotel_room_inventory', sa.Column('price', sa.Unicode(),
                                                    server_default='', nullable=False))
    op.add_column('hotel_room_inventory', sa.Column('staff_price', sa.Unicode(),
                                                    server_default='', nullable=False))
    op.execute("UPDATE hotel_room_inventory SET price = base_price::text WHERE base_price IS NOT NULL")
    op.execute("UPDATE hotel_room_inventory SET staff_price = base_staff_price::text "
               "WHERE base_staff_price IS NOT NULL")
    for col in ('pricing_notes', 'price_per_occupancy', 'price_per_night',
                'base_staff_price', 'base_price'):
        op.drop_column('hotel_room_inventory', col)

    op.add_column('room_assignment', sa.Column('require_cc', sa.Boolean(),
                                               server_default='true', nullable=False))
    op.execute("""
        UPDATE room_assignment
        SET require_cc = payment_type NOT IN ('masterbill', 'masterbill_parking')
    """)
    op.drop_column('room_assignment', 'payment_type')

    op.drop_column('attendee', 'staff_lottery_eligible')

    op.drop_index(op.f('ix_inventory_price_inventory_id'), table_name='inventory_price')
    op.drop_table('inventory_price')
    op.drop_table('import_mapping_template')
