import urllib
from itertools import chain

import cherrypy
from pockets import groupify, listify
from rpctools.jsonrpc import ServerProxy
from sqlalchemy import and_, or_, func

from uber.config import c, _config
from uber.custom_tags import pluralize
from uber.decorators import all_renderable
from uber.errors import HTTPRedirect
from uber.models import Attendee, Department, DeptMembership, DeptMembershipRequest


def _server_to_url(server):
    if not server:
        return ''
    host, _, path = urllib.parse.unquote(server).replace('http://', '').replace('https://', '').partition('/')
    if path.startswith('reggie'):
        return 'https://{}/reggie'.format(host)
    elif path.startswith('uber'):
        return 'https://{}/uber'.format(host)
    elif c.PATH == '/uber':
        return 'https://{}{}'.format(host, c.PATH)
    return 'https://{}'.format(host)


def _server_to_host(server):
    if not server:
        return ''
    return urllib.parse.unquote(server).replace('http://', '').replace('https://', '').split('/')[0]


def _format_import_params(target_server, api_token):
    target_url = _server_to_url(target_server)
    target_host = _server_to_host(target_server)
    remote_api_token = api_token.strip()
    if not remote_api_token:
        remote_api_tokens = _config.get('secret', {}).get('remote_api_tokens', {})
        remote_api_token = remote_api_tokens.get(target_host, remote_api_tokens.get('default', ''))
    return (target_url, target_host, remote_api_token.strip())


@all_renderable()
class Root:
    def import_attendees(self, session, target_server='', api_token='', query='', message=''):
        target_url, target_host, remote_api_token = _format_import_params(target_server, api_token)

        results = {}
        if cherrypy.request.method == 'POST':
            if not remote_api_token:
                message = 'No API token given and could not find a token for: {}'.format(target_host)
            elif not target_url:
                message = 'Unrecognized hostname: {}'.format(target_server)

            if not message:
                try:
                    uri = '{}/jsonrpc/'.format(target_url)
                    service = ServerProxy(uri=uri, extra_headers={'X-Auth-Token': remote_api_token})
                    results = service.attendee.export(query=query)
                except Exception as ex:
                    message = str(ex)

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
        else:
            existing_attendees = []

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

        target_url, target_host, remote_api_token = _format_import_params(target_server, api_token)
        results = {}
        try:
            uri = '{}/jsonrpc/'.format(target_url)
            service = ServerProxy(uri=uri, extra_headers={'X-Auth-Token': remote_api_token})
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
