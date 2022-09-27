from itertools import chain
from uber.models.attendee import AttendeeAccount

import cherrypy
from datetime import datetime
from pockets import groupify, listify
from six import string_types
from sqlalchemy import and_, or_, func
from sqlalchemy.orm import joinedload, raiseload, subqueryload
from sqlalchemy.orm.exc import NoResultFound

from uber.config import c, _config
from uber.custom_tags import datetime_local_filter, pluralize, format_currency
from uber.decorators import ajax, all_renderable, csv_file, not_site_mappable, site_mappable
from uber.errors import HTTPRedirect
from uber.models import AdminAccount, ApiJob, Attendee, ModelReceipt, ReceiptItem, ReceiptTransaction
from uber.site_sections import devtools
from uber.utils import Charge, check, get_api_service_from_server, normalize_email

def check_custom_receipt_item_txn(params, is_txn=False):
    if not params.get('amount'):
        return "You must enter a positive or negative amount."
    
    try:
        amount = int(params['amount'])
    except Exception:
        return "The amount must be a number."

    if amount > 999999 or amount < -999999:
        return "Please enter a realistic number for the amount."
    if amount == 0:
        return "You cannot enter an amount of 0."

    if is_txn:
        if not params.get('method'):
            return "You must choose a payment method."
        if int(params['amount']) < 0 and not params.get('desc'):
            return "You must enter a description when adding a refund."
    elif not params.get('desc'):
        return "You must describe the item you are adding or crediting."

@all_renderable()
class Root:
    def receipt_items(self, session, id, message=''):
        try:
            model = session.attendee(id)
        except NoResultFound:
            model = session.group(id)

        receipt = session.get_receipt_by_model(model)

        other_receipts = set()
        if isinstance(model, Attendee):
            for app in model.art_show_applications:
                other_receipts.add(session.get_receipt_by_model(app))
            
        return {
            'attendee': model if isinstance(model, Attendee) else None,
            'group': model,
            'receipt': receipt,
            'other_receipts': other_receipts,
            'closed_receipts': session.query(ModelReceipt).filter(ModelReceipt.owner_id == id,
                                                                  ModelReceipt.owner_model == model.__class__.__name__,
                                                                  ModelReceipt.closed != None).all(),
            'message': message,
        }

    @ajax
    def add_receipt_item(self, session, id='', **params):
        receipt = session.model_receipt(id)

        message = check_custom_receipt_item_txn(params)
        if message:
            return {'error': message}

        count = params.get('count')
        if count:
            try:
                count = int(params['count'])
            except Exception:
                return {'error': "The count must be a number."}

        session.add(ReceiptItem(receipt_id=receipt.id,
                                desc=params['desc'],
                                amount=int(params.get('amount', 0)) * 100,
                                count=int(count or 1),
                                who=AdminAccount.admin_name() or 'non-admin'
                            ))

        try:
            session.commit()
        except Exception:
            return {'error': "Encountered an exception while trying to save item."}

        return {'success': True}

    @ajax
    def remove_receipt_item(self, session, id='', **params):
        try:
            item = session.receipt_item(id)
        except NoResultFound:
            item = session.receipt_transaction(id)
        
        session.delete(item)
        session.commit()

        return {'removed': id}

    @ajax
    def undo_receipt_item(self, session, id='', **params):
        item = session.receipt_item(id)
        receipt = item.receipt
        model = session.get_model_by_receipt(receipt)
        for col_name in item.revert_change:
            receipt_item = Charge.process_receipt_upgrade_item(model, col_name, receipt=receipt, new_val=item.revert_change[col_name])
            session.add(receipt_item)
            model.apply(item.revert_change, restricted=False)
        
        message = check(model)
        
        if message:
            session.rollback()
            return {'error': message}
        session.commit()

        return {'success': True}

    @ajax
    def add_receipt_txn(self, session, id='', **params):
        receipt = session.model_receipt(id)

        message = check_custom_receipt_item_txn(params, is_txn=True)
        if message:
            return {'error': message}

        session.add(ReceiptTransaction(receipt_id=receipt.id,
                                       amount=int(params.get('amount', 0)) * 100,
                                       method=params.get('method'),
                                       desc=params['desc'],
                                       who=AdminAccount.admin_name() or 'non-admin'
                                    ))

        try:
            session.commit()
        except Exception:
            session.rollback()
            return {'error': "Encountered an exception while trying to save transaction."}

        if (receipt.item_total - receipt.txn_total) <= 0:
            for item in receipt.open_receipt_items:
                item.closed = datetime.now()
                session.add(item)

            session.commit()

        return {'success': True}
        
    @ajax
    def cancel_receipt_txn(self, session, id='', **params):
        txn = session.receipt_transaction(id)
        
        txn.cancelled = datetime.now()
        session.add(txn)
        session.commit()

        return {'cancelled': id, 'time': datetime_local_filter(txn.cancelled)}

    @ajax
    def refund_receipt_txn(self, session, id='', **params):
        txn = session.receipt_transaction(id)
        model = session.get_model_by_receipt(txn.receipt)
        
        if not txn.refund_id and txn.stripe_id:
            response = session.process_refund(txn)
            if response:
                if isinstance(response, string_types):
                    raise HTTPRedirect('../reg_admin/receipt_items?id={}&message={}', model.id, response)

            session.commit()

        return {'refunded': id}
    
    @not_site_mappable
    def process_full_refund(self, session, id='', attendee_id='', group_id=''):
        receipt = session.model_receipt(id)
        refund_total = 0
        for txn in receipt.receipt_txns:
            if not txn.refund_id and txn.stripe_id:
                response = session.process_refund(txn)
                if response:
                    if isinstance(response, string_types):
                        raise HTTPRedirect('../reg_admin/receipt_items?id={}&message={}', attendee_id or group_id, response)
                    refund_total += response.amount

        receipt.closed = datetime.now()
        session.add(receipt)

        if attendee_id:
            model = session.attendee(attendee_id)
            model.badge_status = c.REFUNDED_STATUS
            model.paid = c.REFUNDED

        if group_id:
            model = session.group(group_id)
            model.status = c.CANCELLED
        
        session.add(model)
        
        session.commit()
        raise HTTPRedirect('../reg_admin/receipt_items?id={}&message={}',
                           attendee_id or group_id,
                           "{}'s registration has been cancelled and they have been refunded {}.".format(
                            getattr(model, 'full_name', None) or model.name, format_currency(refund_total / 100)
                           ))

    @not_site_mappable
    def remove_promo_code(self, session, id=''):
        attendee = session.attendee(id)
        attendee.paid = c.NOT_PAID
        attendee.promo_code = None
        attendee.badge_status = c.NEW_STATUS
        raise HTTPRedirect('../registration/form?id={}&message={}', id, "Promo code removed.")

    def attendee_accounts(self, session, message=''):
        return {
            'message': message,
            'accounts': session.query(AttendeeAccount).options(joinedload(AttendeeAccount.attendees), raiseload('*')).all(),
        }

    def delete_attendee_account(self, session, id, message='', **params):
        account = session.attendee_account(id)
        if not account:
            message = "No account found!"
        else:
            session.delete(account)
        raise HTTPRedirect('attendee_accounts?message={}', message or 'Account deleted.')

    @site_mappable
    def orphaned_attendees(self, session, message='', **params):
        from uber.site_sections.preregistration import set_up_new_account

        if cherrypy.request.method == 'POST':
            if 'account_email' not in params:
                message = "Please enter an account email to assign to this attendee."
            else:
                account_email = params.get('account_email').strip()
                attendee = session.attendee(params.get('id'))
                account = session.query(AttendeeAccount).filter_by(normalized_email=normalize_email(account_email)).first()
                if not attendee:
                    message = "Attendee not found!"
                elif not account:
                    set_up_new_account(session, attendee, account_email)
                    session.commit()
                    message = "New account made for {} under email {}.".format(attendee.full_name, account_email)
                else:
                    session.add_attendee_to_account(session.attendee(params.get('id')), account)
                    session.commit()
                    message = "{} is now being managed by account {}.".format(attendee.full_name, account_email)

        return {
            'message': message,
            'attendees': session.query(Attendee).filter(~Attendee.managers.any()).options(raiseload('*')).all(),
        }

    def payment_pending_attendees(self, session):
        possibles = session.possible_match_list()
        attendees = []
        pending = session.query(Attendee).filter_by(paid=c.PENDING).filter(Attendee.badge_status != c.INVALID_STATUS)
        for attendee in pending:
            attendees.append([attendee, set(possibles[attendee.email.lower()] + 
                                            possibles[attendee.first_name, attendee.last_name])])
        return {
            'attendees': attendees,
        }
    
    @ajax
    def invalidate_badge(self, session, id):
        attendee = session.attendee(id)
        attendee.badge_status = c.INVALID_STATUS
        session.add(attendee)

        session.commit()

        return {'invalidated': id}

    def attendees_who_owe_money(self, session):
        # TODO: Use receipts here instead of attendees
        unpaid_attendees = [attendee for attendee in session.attendees_with_badges() 
                            if attendee.total_purchased_cost > attendee.amount_paid]
        return {
            'attendees': unpaid_attendees,
        }

    @csv_file
    @not_site_mappable
    def attendee_search_export(self, out, session, search_text='', order='last_first', invalid=''):
        filter = Attendee.badge_status.in_([c.NEW_STATUS, c.COMPLETED_STATUS, c.WATCHED_STATUS]) if not invalid else None
        
        search_text = search_text.strip()
        if search_text:
            attendees, error = session.search(search_text) if invalid else session.search(search_text, filter)

        if error:
            raise HTTPRedirect('../registration/index?search_text={}&order={}&invalid={}&message={}'
                              ).format(search_text, order, invalid, error)
        attendees = attendees.order(order)

        rows = devtools.prepare_model_export(Attendee, filtered_models=attendees)
        for row in rows:
            out.writerow(row)

    def attendee_account_form(self, session, id, message=''):
        account = session.attendee_account(id)

        return {
            'message': message,
            'account': account,
        }

    @site_mappable
    def import_attendees(self, session, target_server='', api_token='', query='', message='', which_import='', **params):
        service, service_message, target_url = get_api_service_from_server(target_server, api_token)
        message = message or service_message

        attendees, existing_attendees, results = {}, {}, {}
        accounts, existing_accounts = {}, {}
        groups, existing_groups = {}, {}
        results_name, href_base = '', ''

        if service and which_import:
            try:
                if which_import == 'attendees':
                    results = service.attendee.export(query=query)
                    results_name = 'attendees'
                    href_base = '{}/reg_admin/attendee_account_form?id={}'
                elif which_import == 'accounts':
                    results = service.attendee_account.export(query=query, all=params.get('all', False))
                    results_name = 'accounts'
                    href_base = '{}/registration/form?id={}'
                elif which_import == 'groups':
                    if params.get('dealers', ''):
                        results = service.group.dealers(status=params.get('status', None))
                    else:
                        results = service.group.export(query=query)
                    results_name = 'groups'
                    href_base = '{}/group_admin/form?id={}'

            except Exception as ex:
                message = str(ex)

        if cherrypy.request.method == 'POST' and not message:
            models = results.get(results_name, [])
            for model in models:
                model['href'] = href_base.format(target_url, model['id'])

            if models and which_import == 'attendees':
                attendees = models
                attendees_by_name_email = groupify(attendees, lambda a: (
                    a['first_name'].lower(),
                    a['last_name'].lower(),
                    normalize_email(a['email']),
                ))

                filters = [
                    and_(
                        func.lower(Attendee.first_name) == first,
                        func.lower(Attendee.last_name) == last,
                        Attendee.normalized_email == email,
                    )
                    for first, last, email in attendees_by_name_email.keys()
                ]

                existing_attendees = session.query(Attendee).filter(or_(*filters)).all()
                for attendee in existing_attendees:
                    existing_key = (attendee.first_name.lower(), attendee.last_name.lower(), attendee.normalized_email)
                    attendees_by_name_email.pop(existing_key, {})
                attendees = list(chain(*attendees_by_name_email.values()))

            if models and which_import == 'accounts':
                accounts = models
                accounts_by_email = groupify(accounts, lambda a: normalize_email(a['email']))

                existing_accounts = session.query(AttendeeAccount).filter(
                    AttendeeAccount.normalized_email.in_(accounts_by_email.keys())) \
                    .options(subqueryload(AttendeeAccount.attendees)).all()
                for account in existing_accounts:
                    existing_key = account.normalized_email
                    accounts_by_email.pop(existing_key, {})
                accounts = list(chain(*accounts_by_email.values()))

            if models and which_import == 'groups':
                groups = models
                groups_by_name = groupify(groups, lambda g: g['name'])

                """existing_groups = session.query(Group).filter(Group.name.in_(groups_by_name.keys())) \
                    .options(subqueryload(Group.attendees)).all()
                for group in existing_groups:
                    existing_key = group.name
                    groups_by_name.pop(existing_key, {})"""
                groups = list(chain(*groups_by_name.values()))

        return {
            'target_server': target_server,
            'api_token': api_token,
            'query': query,
            'message': message,
            'which_import': which_import,
            'unknown_ids': results.get('unknown_ids', []),
            'unknown_emails': results.get('unknown_emails', []),
            'unknown_names': results.get('unknown_names', []),
            'unknown_names_and_emails': results.get('unknown_names_and_emails', []),
            'attendees': attendees,
            'existing_attendees': existing_attendees,
            'accounts': accounts,
            'existing_accounts': existing_accounts,
            'groups': groups,
            'existing_groups': existing_groups,
        }

    def confirm_import_attendees(self, session, badge_type, admin_notes, target_server, api_token, query, attendee_ids):
        if cherrypy.request.method != 'POST':
            raise HTTPRedirect('import_attendees?target_server={}&api_token={}&query={}',
                               target_server,
                               api_token,
                               query)

        admin_id = cherrypy.session.get('account_id')
        admin_name = session.admin_attendee().full_name
        already_queued = 0
        attendee_ids = attendee_ids if isinstance(attendee_ids, list) else [attendee_ids]

        for id in attendee_ids:
            existing_import = session.query(ApiJob).filter(ApiJob.job_name == "attendee_import",
                                            ApiJob.query == id,
                                            ApiJob.cancelled == None,
                                            ApiJob.errors == '').count()
            if existing_import:
                already_queued += 1
            else:
                session.add(ApiJob(
                    admin_id = admin_id,
                    admin_name = admin_name,
                    job_name = "attendee_import",
                    target_server = target_server,
                    api_token = api_token,
                    query = id,
                    json_data = {'badge_type': badge_type, 'admin_notes': admin_notes, 'full': True}
                ))
            session.commit()

        attendee_count = len(attendee_ids) - already_queued
        badge_label = c.BADGES[int(badge_type)].lower()

        if len(attendee_ids) > 100:
            query = '' # Clear very large queries to prevent 502 errors

        raise HTTPRedirect(
            'import_attendees?target_server={}&api_token={}&query={}&message={}',
            target_server,
            api_token,
            query,
            '{count} attendee{s} imported with {a}{badge_label} badge{s}.{queued}'.format(
                count=attendee_count,
                s=pluralize(attendee_count),
                a=pluralize(attendee_count, singular='an ' if badge_label.startswith('a') else 'a ', plural=''),
                badge_label=badge_label,
                queued='' if not already_queued else ' {} badges are already queued for import.'.format(already_queued),
            )
        )

    def confirm_import_attendee_accounts(self, session, target_server, api_token, query, account_ids):
        if cherrypy.request.method != 'POST':
            raise HTTPRedirect('import_attendees?target_server={}&api_token={}&query={}&which_import={}',
                               target_server,
                               api_token,
                               query,
                               'accounts')

        admin_id = cherrypy.session.get('account_id')
        admin_name = session.admin_attendee().full_name
        already_queued = 0
        account_ids = account_ids if isinstance(account_ids, list) else [account_ids]

        for id in account_ids:
            existing_import = session.query(ApiJob).filter(ApiJob.job_name == "attendee_account_import",
                                            ApiJob.query == id,
                                            ApiJob.completed == None,
                                            ApiJob.cancelled == None,
                                            ApiJob.errors == '').count()
            if existing_import:
                already_queued += 1
            else:
                session.add(ApiJob(
                    admin_id = admin_id,
                    admin_name = admin_name,
                    job_name = "attendee_account_import",
                    target_server = target_server,
                    api_token = api_token,
                    query = id,
                    json_data = {'all': False}
                ))
            session.commit()

        attendee_count = len(account_ids) - already_queued

        if len(account_ids) > 100:
            query = '' # Clear very large queries to prevent 502 errors

        raise HTTPRedirect(
            'import_attendees?target_server={}&api_token={}&query={}&message={}&which_import={}',
            target_server,
            api_token,
            query,
            '{count} attendee account{s} queued for import.{queued}'.format(
                count=attendee_count,
                s=pluralize(attendee_count),
                queued='' if not already_queued else ' {} accounts are already queued for import.'.format(already_queued),
            ),
            'accounts',
        )
    
    def confirm_import_groups(self, session, target_server, api_token, query, group_ids):
        if cherrypy.request.method != 'POST':
            raise HTTPRedirect('import_attendees?target_server={}&api_token={}&query={}&which_import={}',
                               target_server,
                               api_token,
                               query,
                               'groups')

        admin_id = cherrypy.session.get('account_id')
        admin_name = session.admin_attendee().full_name
        already_queued = 0
        group_ids = group_ids if isinstance(group_ids, list) else [group_ids]

        for id in group_ids:
            existing_import = session.query(ApiJob).filter(ApiJob.job_name == "group_import",
                                            ApiJob.query == id,
                                            ApiJob.completed == None,
                                            ApiJob.cancelled == None,
                                            ApiJob.errors == '').count()
            if existing_import:
                already_queued += 1
            else:
                session.add(ApiJob(
                    admin_id = admin_id,
                    admin_name = admin_name,
                    job_name = "group_import",
                    target_server = target_server,
                    api_token = api_token,
                    query = id,
                    json_data = {'all': True}
                ))
            session.commit()

        attendee_count = len(group_ids) - already_queued

        if len(group_ids) > 100:
            query = '' # Clear very large queries to prevent 502 errors

        raise HTTPRedirect(
            'import_attendees?target_server={}&api_token={}&query={}&message={}&which_import={}',
            target_server,
            api_token,
            query,
            '{count} group{s} queued for import.{queued}'.format(
                count=attendee_count,
                s=pluralize(attendee_count),
                queued='' if not already_queued else ' {} groups are already queued for import.'.format(already_queued),
            ),
            'groups',
        )
