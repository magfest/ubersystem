from itertools import chain

import cherrypy
from pockets import groupify, listify
from sqlalchemy import and_, or_, func

from uber.config import c, _config
from uber.custom_tags import pluralize
from uber.decorators import all_renderable
from uber.errors import HTTPRedirect
from uber.models import Attendee, Department, DeptMembership, DeptMembershipRequest
from uber.utils import get_api_service_from_server


@all_renderable()
class Root:
    def receipt_items(self, session, id, message=''):
        attendee = session.attendee(id)

        return {
            'attendee': attendee,
            'message': message,
            'stripe_txn_opts': [(txn.stripe_transaction.id, txn.stripe_transaction.stripe_id)
                                for txn in attendee.stripe_txn_share_logs],
        }

    def add_receipt_item(self, session, id='', **params):
        attendee = session.attendee(id)
        stripe_txn_id = params.get('stripe_txn_id', '')
        if stripe_txn_id:
            stripe_txn = session.stripe_transaction(stripe_txn_id)

        session.add(session.create_receipt_item(
            attendee, int(params.get('amount')) * 100, params.get('desc'), stripe_txn if stripe_txn_id else None,
            params.get('item_type'), params.get('txn_type')))

        raise HTTPRedirect('receipt_items?id={}&message={}', attendee.id, "Receipt Item added")

    def remove_receipt_item(self, session, id='', **params):
        item = session.receipt_item(id)
        attendee_or_group = item.attendee if item.attendee_id else item.group_id
        session.delete(item)

        raise HTTPRedirect('receipt_items?id={}&message={}', attendee_or_group.id, "Receipt Item deleted")

    def remove_promo_code(self, session, id=''):
        attendee = session.attendee(id)
        attendee.paid = c.NOT_PAID
        attendee.promo_code = None
        attendee.badge_status = c.NEW_STATUS
        raise HTTPRedirect('../registration/form?id={}&message={}', id, "Promo code removed.")

    def import_attendees(self, session, target_server='', api_token='', query='', message=''):
        service, service_message, target_url = get_api_service_from_server(target_server, api_token)
        message = message or service_message

        attendees, existing_attendees, results = {}, {}, {}

        if service:
            try:
                results = service.attendee.export(query=query)
            except Exception as ex:
                message = str(ex)

        if cherrypy.request.method == 'POST' and not message:
            attendees = results.get('attendees', [])
            for attendee in attendees:
                attendee['href'] = '{}/registration/form?id={}'.format(target_url, attendee['id'])

            if attendees:
                attendees_by_name_email = groupify(attendees, lambda a: (
                    a['first_name'].lower(),
                    a['last_name'].lower(),
                    Attendee.normalize_email(a['email']),
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

        return {
            'target_server': target_server,
            'api_token': api_token,
            'query': query,
            'message': message,
            'unknown_ids': results.get('unknown_ids', []),
            'unknown_emails': results.get('unknown_emails', []),
            'unknown_names': results.get('unknown_names', []),
            'unknown_names_and_emails': results.get('unknown_names_and_emails', []),
            'attendees': attendees,
            'existing_attendees': existing_attendees,
        }

    def confirm_import_attendees(self, session, badge_type, admin_notes, target_server, api_token, query, attendee_ids):
        if cherrypy.request.method != 'POST':
            raise HTTPRedirect('import_attendees?target_server={}&api_token={}&query={}',
                               target_server,
                               api_token,
                               query)

        service, message, target_url = get_api_service_from_server(target_server, api_token)

        try:
            results = service.attendee.export(query=','.join(listify(attendee_ids)), full=True)
        except Exception as ex:
            raise HTTPRedirect(
                'import_attendees?target_server={}&api_token={}&query={}&message={}',
                target_server, remote_api_token, query, str(ex))

        depts = {}

        def _guess_dept(id_name):
            id, name = id_name
            if id in depts:
                return (id, depts[id])

            dept = session.query(Department).filter(or_(
                Department.id == id,
                Department.normalized_name == Department.normalize_name(name))).first()

            if dept:
                depts[id] = dept
                return (id, dept)
            return None

        badge_type = int(badge_type)
        badge_label = c.BADGES[badge_type].lower()

        attendees = results.get('attendees', [])
        for d in attendees:
            import_from_url = '{}/registration/form?id={}\n\n'.format(target_url, d['id'])
            new_admin_notes = '{}\n\n'.format(admin_notes) if admin_notes else ''
            old_admin_notes = 'Old Admin Notes:\n{}\n'.format(d['admin_notes']) if d['admin_notes'] else ''

            d.update({
                'badge_type': badge_type,
                'badge_status': c.NEW_STATUS,
                'paid': c.NEED_NOT_PAY,
                'placeholder': True,
                'requested_hotel_info': True,
                'admin_notes': 'Imported {} from {}{}{}'.format(
                    badge_label, import_from_url, new_admin_notes, old_admin_notes),
                'past_years': d['all_years'],
            })
            del d['id']
            del d['all_years']

            if badge_type != c.STAFF_BADGE:
                attendee = Attendee().apply(d, restricted=False)

            else:
                assigned_depts = {d[0]: d[1] for d in map(_guess_dept, d.pop('assigned_depts', {}).items()) if d}
                checklist_admin_depts = d.pop('checklist_admin_depts', {})
                dept_head_depts = d.pop('dept_head_depts', {})
                poc_depts = d.pop('poc_depts', {})
                requested_depts = d.pop('requested_depts', {})

                d.update({
                    'staffing': True,
                    'ribbon': str(c.DEPT_HEAD_RIBBON) if dept_head_depts else '',
                })

                attendee = Attendee().apply(d, restricted=False)

                for id, dept in assigned_depts.items():
                    attendee.dept_memberships.append(DeptMembership(
                        department=dept,
                        attendee=attendee,
                        is_checklist_admin=bool(id in checklist_admin_depts),
                        is_dept_head=bool(id in dept_head_depts),
                        is_poc=bool(id in poc_depts),
                    ))

                requested_anywhere = requested_depts.pop('All', False)
                requested_depts = {d[0]: d[1] for d in map(_guess_dept, requested_depts.items()) if d}

                if requested_anywhere:
                    attendee.dept_membership_requests.append(DeptMembershipRequest(attendee=attendee))
                for id, dept in requested_depts.items():
                    attendee.dept_membership_requests.append(DeptMembershipRequest(
                        department=dept,
                        attendee=attendee,
                    ))

            session.add(attendee)

        attendee_count = len(attendees)
        raise HTTPRedirect(
            'import_attendees?target_server={}&api_token={}&query={}&message={}',
            target_server,
            api_token,
            query,
            '{count} attendee{s} imported with {a}{badge_label} badge{s}'.format(
                count=attendee_count,
                s=pluralize(attendee_count),
                a=pluralize(attendee_count, singular='an ' if badge_label.startswith('a') else 'a ', plural=''),
                badge_label=badge_label,
            )
        )
