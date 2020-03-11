"""Add many-to-many tables for stripe transactions

Revision ID: e372e4daf771
Revises: f142e4d54e49
Create Date: 2018-08-31 20:42:18.905795

"""


# revision identifiers, used by Alembic.
revision = 'e372e4daf771'
down_revision = 'f142e4d54e49'
branch_labels = None
depends_on = None

import residue
import sqlalchemy as sa
import uuid
import json
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql import and_, or_, table

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

stripe_txn_table = table(
    'stripe_transaction',
    sa.Column('id', residue.UUID()),
    sa.Column('amount', sa.Integer()),
    sa.Column('desc', sa.Unicode()),
    sa.Column('fk_id', residue.UUID()),
    sa.Column('fk_model', sa.Unicode())
)

attendee_table = table(
    'attendee',
    sa.Column('id', residue.UUID()),
    sa.Column('first_name', sa.Unicode()),
    sa.Column('last_name', sa.Unicode()),
    sa.Column('paid', sa.Integer()),
    sa.Column('amount_paid', sa.Integer()),
    sa.Column('amount_extra', sa.Integer())
)

group_table = table(
    'group',
    sa.Column('id', residue.UUID()),
    sa.Column('leader_id', residue.UUID()),
    sa.Column('name', sa.Unicode()),
    sa.Column('amount_paid', sa.Integer())
)

attendee_txn_table = table(
    'stripe_transaction_attendee',
    sa.Column('id', residue.UUID()),
    sa.Column('txn_id', residue.UUID()),
    sa.Column('attendee_id', residue.UUID()),
    sa.Column('share', sa.Integer())
)

group_txn_table = table(
    'stripe_transaction_group',
    sa.Column('id', residue.UUID()),
    sa.Column('txn_id', residue.UUID()),
    sa.Column('group_id', residue.UUID()),
    sa.Column('share', sa.Integer())
)

tracking_table = table(
    'tracking',
    sa.Column('fk_id', residue.UUID()),
    sa.Column('model', sa.Unicode()),
    sa.Column('action', sa.Integer()),
    sa.Column('snapshot', sa.Unicode()),
)

from uber.config import c


def get_model_share(id, model):
    connection = op.get_bind()

    # Models in a multi-model transaction are ALWAYS being created for the first time
    # It's impossible for someone to pay again for multiple attendees/groups at once
    [model_creation] = connection.execute(
        tracking_table.select().where(and_(
            tracking_table.c.fk_id == id,
            tracking_table.c.model == model,
            tracking_table.c.action == c.CREATED
        )
        )
    )

    try:
        return int(json.loads(model_creation.snapshot)['amount_paid']) * 100, None
    except Exception as e:
        return None, "Error: could not get amount paid from tracking table for {} {}. ({})" \
            .format(model, id, e)


def add_attendee_txn(txn, attendee, share=None):
    if not share:
        share, error = get_model_share(attendee.id, 'Attendee')
        if error:
            return error

    op.execute(
        attendee_txn_table.insert().values({
            'id': str(uuid.uuid4()),
            'txn_id': txn.id,
            'attendee_id': attendee.id,
            'share': share
        })
    )

def add_group_txn(txn, group, share=None):
    if not share:
        share, error = get_model_share(group.id, 'Group')
        if error:
            return error

    op.execute(
        group_txn_table.insert().values({
            'id': str(uuid.uuid4()),
            'txn_id': txn.id,
            'group_id': group.id,
            'share': share
        })
    )


def add_model_by_txn(txn, multi=False):
    # Adds a model according to the fk_model stored on a transaction, and returns its name
    connection = op.get_bind()

    share = txn.amount if not multi else None

    if txn.fk_model == "Attendee":
        attendees = [a for a in connection.execute(
            attendee_table.select().where(
                attendee_table.c.id == txn.fk_id
            )
        )]

        if len(attendees) == 1:
            [attendee] = attendees
            if txn.amount <= attendee.amount_paid or multi:
                error = add_attendee_txn(txn, attendee, share)
                return ('', '', error) if error else (attendee.first_name, attendee.last_name, None)
            else:
                return '', '', "The transaction for {} is more than their amount_paid."\
                    .format(attendee.first_name + " " + attendee.last_name)

    elif txn.fk_model == "Group":
        groups = [g for g in connection.execute(
            group_table.select().where(
                group_table.c.id == txn.fk_id
            )
        )]

        if len(groups) == 1:
            [group] = groups
            if txn.amount <= group.amount_paid or multi:
                error = add_group_txn(txn, group, share)
                return ('', '', error) if error else (group.name, '', None)
            else:
                [group_leader] = connection.execute(
                    attendee_table.select().where(
                        attendee_table.c.id == group.leader_id
                    )
                )
                if group_leader.amount_extra:
                    txn_guess = group.amount_paid + (group_leader.amount_extra * 100)
                    if txn.amount <= txn_guess:
                        error = add_group_txn(txn, group, share)
                        if error:
                            return '', '', error
                        error = add_attendee_txn(txn, group_leader)
                        return ('', '', error) if error else (group.name, '', None)

                return '', '', "The transaction for the group {} is more than its amount_paid." \
                    .format(group.name)

    return '', '', '{} not found for ID {}'.format(txn.fk_model, txn.fk_id)

def upgrade():
    op.create_table('stripe_transaction_group',
    sa.Column('id', residue.UUID(), nullable=False),
    sa.Column('txn_id', residue.UUID(), nullable=False),
    sa.Column('group_id', residue.UUID(), nullable=False),
    sa.Column('share', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['group_id'], ['group.id'], name=op.f('fk_stripe_transaction_group_group_id_group')),
    sa.ForeignKeyConstraint(['txn_id'], ['stripe_transaction.id'], name=op.f('fk_stripe_transaction_group_txn_id_stripe_transaction')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_stripe_transaction_group'))
    )
    op.create_table('stripe_transaction_attendee',
    sa.Column('id', residue.UUID(), nullable=False),
    sa.Column('txn_id', residue.UUID(), nullable=False),
    sa.Column('attendee_id', residue.UUID(), nullable=False),
    sa.Column('share', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['attendee_id'], ['attendee.id'], name=op.f('fk_stripe_transaction_attendee_attendee_id_attendee')),
    sa.ForeignKeyConstraint(['txn_id'], ['stripe_transaction.id'], name=op.f('fk_stripe_transaction_attendee_txn_id_stripe_transaction')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_stripe_transaction_attendee'))
    )

    connection = op.get_bind()

    txns = connection.execute(
        stripe_txn_table.select()
    )

    errors = []

    group_names = [group.name for group in
                   connection.execute(group_table.select())]

    comma_attendees = [a.first_name + " " + a.last_name
                       for a in connection.execute(
            attendee_table.select()
        ) if ',' in a.first_name or ',' in a.last_name]

    comma_groups = [g.name for g in connection.execute(
        group_table.select()
    ) if ',' in g.name]

    for txn in txns:
        if ', ' in txn.desc:
            desc = txn.desc
            comma_names = []

            for name in (comma_attendees + comma_groups):
                if name in desc:
                    desc = desc.replace(name, '', 1)
                    comma_names.append(name)

            name_list = desc.split(', ') + comma_names if comma_names else desc.split(', ')
            first_name, last_name, error = add_model_by_txn(txn, True)
            saved_name = first_name + " " + last_name if txn.fk_model == "Attendee" else first_name

            if error:
                errors.append(error)
            else:
                if txn.fk_model == "Attendee":
                    # We change attendees' name case in the DB, but not groups'
                    # We want to remove names without title casing first
                    # but only if there's no groups with that name
                    for name in name_list:
                        if first_name.upper() in name:
                            remove_name = first_name.upper()
                        elif first_name.lower() in name:
                            remove_name = first_name.lower()
                        else:
                            remove_name = first_name

                        if last_name.upper() in name:
                            remove_name = remove_name + " " + last_name.upper()
                        elif last_name.lower() in name:
                            remove_name = remove_name + " " + last_name.lower()
                        else:
                            remove_name = remove_name + " " + last_name

                        if remove_name not in group_names and remove_name in name_list:
                            name_list.remove(remove_name)
                            break
                else:
                    name_list.remove(saved_name)

            for name in name_list:
                if not name:
                    # This happens for single attendee transactions
                    # where the attendee used a ', ' in their name
                    continue

                matching_groups = [txn for txn in connection.execute(
                    group_table.select().where(and_(
                        group_table.c.id != txn.fk_id,
                        group_table.c.name == name
                    )
                    )
                )]

                # This only exists for one loop if we set it outside the loop
                attendees = connection.execute(
                    attendee_table.select()
                )

                # This is a presave adjustment we make after the charge, but before saving an attendee
                if name.isupper() or name.islower():
                    name = name.title()

                matching_attendees = [a for a in attendees if a.first_name + " " + a.last_name == name and a.id != txn.fk_id]

                if not matching_attendees and not matching_groups:
                    errors.append('Error: name not found for "{}"'.format(name))
                    continue

                if len(matching_attendees+matching_groups) != name_list.count(name):
                    if "kicking in" in txn.desc:
                        kickin_attendees = [a for a in matching_attendees if a.amount_extra > 0]
                        if len(kickin_attendees == 1):
                            [attendee] = kickin_attendees
                            add_attendee_txn(txn, attendee, txn.amount)
                            continue

                    if len(matching_groups) == 1 and "extra badges" in txn.desc:
                        [group] = matching_groups
                        add_group_txn(txn, group, txn.amount)
                        continue

                    non_group_attendees = [a for a in matching_attendees if a.paid != c.PAID_BY_GROUP]
                    if len(non_group_attendees) == 1:
                        [attendee] = non_group_attendees
                        add_attendee_txn(txn, attendee)
                        continue

                    errors.append('Error: there are {} attendees/groups named "{}" in the DB, but {} in the transaction'
                                  .format(len(matching_attendees+matching_groups), name, name_list.count(name)))
                    name_list = [n for n in name_list if n != name]
                    continue

                for attendee in matching_attendees:
                    add_attendee_txn(txn, attendee)

                for group in matching_groups:
                    add_group_txn(txn, group)
        else:
            first_name, last_name, error = add_model_by_txn(txn)
            if error:
                errors.append(error)

    for error in errors:
        print(error)

    op.drop_column('stripe_transaction', 'fk_id')
    op.drop_column('stripe_transaction', 'fk_model')


def downgrade():
    """
    Comment out everything but the drop_table commands while you're testing
    That way you can freely downgrade and upgrade without destroying data
    """
    op.add_column('stripe_transaction', sa.Column('fk_model', sa.VARCHAR(), server_default=sa.text("''::character varying"), autoincrement=False, nullable=False))
    op.add_column('stripe_transaction', sa.Column('fk_id', postgresql.UUID(), server_default=str(uuid.uuid4()), autoincrement=False, nullable=False))

    connection = op.get_bind()
    txns = connection.execute(
        stripe_txn_table.select()
    )

    for txn in txns:
        attendee_txns = [txn for txn in connection.execute(
            attendee_txn_table.select().where(
                attendee_txn_table.c.txn_id == txn.id
            )
        )]
        group_txns = [txn for txn in connection.execute(
            group_txn_table.select().where(
                group_txn_table.c.txn_id == txn.id
            )
        )]
        if attendee_txns:
            connection.execute(
                stripe_txn_table.update().where(stripe_txn_table.c.id == txn.id).values({
                    'fk_model': "Attendee",
                    'fk_id': attendee_txns[0].attendee_id
                })
            )
        elif group_txns:
            connection.execute(
                stripe_txn_table.update().where(
                    stripe_txn_table.c.id == txn.id).values({
                    'fk_model': "Group",
                    'fk_id': group_txns[0].group_id
                })
            )

    op.alter_column('stripe_transaction', 'fk_id', server_default=None)

    op.drop_table('stripe_transaction_attendee')
    op.drop_table('stripe_transaction_group')

