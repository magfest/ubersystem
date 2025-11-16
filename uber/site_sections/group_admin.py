import cherrypy

from collections import defaultdict
from datetime import datetime
from pockets import readable_join
from pockets.autolog import log
from pytz import UTC
from sqlalchemy import and_, or_
from sqlalchemy.orm import joinedload

from uber.config import c
from uber.custom_tags import format_currency
from uber.decorators import ajax, any_admin_access, all_renderable, csrf_protected, log_pageview
from uber.errors import HTTPRedirect
from uber.forms import load_forms
from uber.models import AdminAccount, Attendee, Email, Event, Group, GuestGroup, PageViewTracking, Tracking
from uber.utils import check, validate_model, add_opt, SignNowRequest
from uber.payments import ReceiptManager


@all_renderable()
class Root:
    def _required_message(self, params, fields):
        missing = [s for s in fields if not params.get(s, '').strip() or params.get(s, '') == "0"]
        if missing:
            return '{} {} required field{}'.format(
                readable_join([s.replace('_', ' ').title() for s in missing]),
                'is a' if len(missing) == 1 else 'are',
                's' if len(missing) > 1 else '')
        return ''

    def index(self, session, message='', show_all=None):
        groups = session.viewable_groups().options(joinedload(Group.attendees))
        dealer_counts = defaultdict(int)

        if not show_all:
            groups = groups.filter(Group.status != c.IMPORTED)

        dealer_groups = groups.filter(Group.is_dealer == True)  # noqa: E712
        dealer_counts['total'] = dealer_groups.count()
        for group in dealer_groups:
            dealer_counts['tables'] += group.tables
            dealer_counts['badges'] += group.badges
            match group.status:
                case c.UNAPPROVED:
                    dealer_counts['unapproved'] += group.tables
                case c.WAITLISTED:
                    dealer_counts['waitlisted'] += group.tables
                case c.APPROVED:
                    dealer_counts['approved'] += group.tables
                case c.SHARED:
                    dealer_counts['approved'] += group.tables

        guest_groups = groups.filter(Group.guest != None)

        return {
            'message': message,
            'show_all': show_all,
            'all_groups': groups,
            'guest_groups': guest_groups,
            'dealer_groups': dealer_groups.options(joinedload(Group.active_receipt)),
            'guest_checklist_items': GuestGroup(group_type=c.GUEST).sorted_checklist_items,
            'band_checklist_items': GuestGroup(group_type=c.BAND).sorted_checklist_items,
            'num_dealer_groups': dealer_counts['total'],
            'dealer_badges': dealer_counts['badges'],
            'tables': dealer_counts['tables'],
            'unapproved_tables': dealer_counts['unapproved'],
            'waitlisted_tables': dealer_counts['waitlisted'],
            'approved_tables': dealer_counts['approved'],
        }

    def new_group_from_attendee(self, session, id):
        attendee = session.attendee(id)
        if attendee.group:
            if c.HAS_REGISTRATION_ACCESS:
                link = '../registration/form?id={}&'.format(attendee.id)
            else:
                link = '../accounts/homepage?'
            raise HTTPRedirect('{}message={}', link, "That attendee is already in a group!")
        group = Group(name="{}'s Group".format(attendee.full_name))
        attendee.group = group
        group.leader = attendee
        session.add(group)

        raise HTTPRedirect('form?id={}&message={}', group.id, "Group successfully created.")

    @log_pageview
    def form(self, session, new_dealer='', message='', **params):
        reg_station_id = cherrypy.session.get('reg_station', '')

        if params.get('id') not in [None, '', 'None']:
            group = session.group(params.get('id'))
            if not session.admin_group_max_access(group):
                raise HTTPRedirect('index?message={}', f"You are not allowed to view this group. If you think this is an error, \
                                   please email us at {c.DEVELOPER_EMAIL}")
            if cherrypy.request.method == 'POST':
                receipt_items = ReceiptManager.auto_update_receipt(group, session.get_receipt_by_model(group), params.copy())
                session.add_all(receipt_items)
        else:
            group = Group(is_dealer=True, tables=1) if new_dealer else Group()

        if group.is_dealer:
            form_list = ['AdminTableInfo', 'ContactInfo']
        else:
            form_list = ['AdminGroupInfo']

        if group.is_new:
            form_list.append('LeaderInfo')

        forms = load_forms(params, group, form_list)
        for form_name, form in forms.items():
            if cherrypy.request.method != 'POST':
                if hasattr(form, 'new_badge_type') and not params.get('new_badge_type'):
                    form['new_badge_type'].data = group.leader.badge_type if group.leader else c.ATTENDEE_BADGE
                if hasattr(form, 'new_ribbons') and not params.get('new_ribbons'):
                    form['new_ribbons'].data = group.leader.ribbon_ints if group.leader else []
                if hasattr(form, 'guest_group_type') and not params.get('guest_group_type') and group.guest:
                    form['guest_group_type'].data = group.guest.group_type
            form.populate_obj(group, is_admin=True)

        signnow_last_emailed = None
        signnow_signed = False
        if c.SIGNNOW_DEALER_TEMPLATE_ID and group.is_dealer and group.status in c.DEALER_ACCEPTED_STATUSES:
            if cherrypy.request.method == 'POST':
                signnow_request = SignNowRequest(session=session, group=group,
                                                 ident="terms_and_conditions", create_if_none=True)
            else:
                signnow_request = SignNowRequest(session=session, group=group)

            if not signnow_request.error_message and signnow_request.document:
                session.add(signnow_request.document)

                signnow_signed = signnow_request.document.signed
                if not signnow_signed:
                    signnow_signed = signnow_request.get_doc_signed_timestamp()
                    if signnow_signed:
                        signnow_signed = datetime.fromtimestamp(int(signnow_signed))
                        signnow_request.document.signed = signnow_signed
                        signnow_link = ''
                        signnow_request.document.link = signnow_link

                if not signnow_signed and not signnow_request.document.last_emailed:
                    signnow_request.send_dealer_signing_invite()
                    signnow_request.document.last_emailed = datetime.now(UTC)

                signnow_last_emailed = signnow_request.document.last_emailed
                session.commit()

        group_info_form = forms.get('group_info', forms.get('table_info'))

        if cherrypy.request.method == 'POST':
            session.add(group)

            if group.is_new and group.guest_group_type:
                group.auto_recalc = False

            if group.is_new or group.badges != group_info_form.badges.data:
                if c.ADMIN_BADGES_NEED_APPROVAL and not session.current_admin_account().full_registration_admin:
                    new_badge_status = c.PENDING_STATUS
                else:
                    new_badge_status = c.NEW_STATUS
                message = session.assign_badges(
                    group,
                    group_info_form.badges.data or int(bool(group.leader_first_name)),
                    new_badge_type=group.new_badge_type,
                    new_ribbon_type=group.new_ribbons,
                    badge_status=new_badge_status,
                    )

            if group.is_dealer and group.status == c.SHARED:
                if group.table_shares:
                    message = ("This group has shared tables connected to it. "
                               "If there are more than two tables sharing a spot, "
                               "please connect the other tables to this group instead.")
                if not message and 'shared_with_name' in params:
                    shared_with_name = params.pop('shared_with_name')
                    if shared_with_name != group.shared_with_name:
                        try:
                            group.set_shared_with_name(shared_with_name)
                        except ValueError as e:
                            message = str(e)

            if not message and group.is_new and group.leader_first_name and group.badges > 0:
                session.commit()
                leader = group.leader = group.attendees[0]
                leader.placeholder = True
                leader.badge_type = group.new_badge_type
                leader.ribbon_ints = group.new_ribbons
                leader_params = {key[7:]: val for key, val in params.items() if key.startswith('leader_')}
                leader_forms = load_forms(leader_params, leader, ['PersonalInfo'])
                all_errors = validate_model(leader_forms, leader, is_admin=True)
                if all_errors:
                    session.delete(group)
                    session.commit()
                    message = ' '.join([item for sublist in all_errors.values() for item in sublist])
                else:
                    forms['personal_info'] = leader_forms['personal_info']
                    forms['personal_info'].populate_obj(leader, is_admin=True)

            if not message:
                if group.guest_group_type:
                    group.guest = group.guest or GuestGroup()
                    group.guest.group_type = group.guest_group_type
                    if params.get('payment', None):
                        group.guest.payment = 1
                    else:
                        group.guest.payment = 0
                elif group.guest:
                    session.delete(group.guest)

                if group.is_new and group.is_dealer:
                    if group.status in c.DEALER_ACCEPTED_STATUSES and group.amount_unpaid:
                        raise HTTPRedirect('../preregistration/group_members?id={}', group.id)
                    elif group.status == c.APPROVED:
                        raise HTTPRedirect(
                            'index?message={}', group.name + ' has been uploaded and approved')
                    else:
                        raise HTTPRedirect(
                            'index?message={}', group.name + ' is uploaded as ' + group.status_label)
                elif group.is_dealer:
                    if group.status in c.DEALER_ACCEPTED_STATUSES and group.orig_value_of('status') not in [c.APPROVED,
                                                                                                        c.SHARED]:
                        for attendee in group.attendees:
                            attendee.ribbon = add_opt(attendee.ribbon_ints, c.DEALER_RIBBON)
                            session.add(attendee)

                raise HTTPRedirect('form?id={}&message={}', group.id, message or (group.name + " has been saved"))

        receipt = session.get_receipt_by_model(group) if not group.is_new else None

        return {
            'message': message,
            'group': group,
            'receipt': receipt,
            'forms': forms,
            'signnow_last_emailed': signnow_last_emailed,
            'signnow_signed': signnow_signed,
            'new_dealer': new_dealer,
            'payment_enabled': True if reg_station_id else False,
        }

    @ajax
    @any_admin_access
    def validate_group(self, session, form_list=[], new_dealer='', **params):
        if params.get('id') in [None, '', 'None']:
            group = Group()
        else:
            group = session.group(params.get('id'))

        if not form_list:
            if group.is_dealer or new_dealer:
                form_list = ['AdminTableInfo', 'ContactInfo']
            else:
                form_list = ['AdminGroupInfo']

            if group.is_new:
                form_list.append('LeaderInfo')
        elif isinstance(form_list, str):
            form_list = [form_list]
        forms = load_forms(params, group, form_list)

        all_errors = validate_model(forms, group, is_admin=True)
        if all_errors:
            return {"error": all_errors}

        return {"success": True}

    def paid_with_cash(self, session, id):
        if not cherrypy.session.get('reg_station'):
            return {'success': False, 'message': 'You must set a workstation ID to take payments.'}

        group = session.group(id)
        receipt = session.get_receipt_by_model(group, create_if_none="DEFAULT")
        amount_owed = receipt.current_amount_owed
        if not amount_owed:
            raise HTTPRedirect('form?id={}&message={}', id, "This group does not owe any money.")

        receipt_manager = ReceiptManager(receipt)
        error = receipt_manager.create_payment_transaction(f"Marked as paid with cash by {AdminAccount.admin_name()}",
                                                           amount=amount_owed, method=c.CASH)
        if error:
            session.rollback()
            raise HTTPRedirect('form?id={}&message={}', id, f"An error occurred: {error}")

        session.add_all(receipt_manager.items_to_add)
        session.commit()
        session.check_receipt_closed(receipt)
        raise HTTPRedirect('form?id={}&message={}', id,
                           f"Cash payment of {format_currency(amount_owed / 100)} recorded.")

    def history(self, session, id):
        group = session.group(id)

        if group.leader:
            other_emails = session.query(Email).filter(
                Email.to == group.leader.email).order_by(Email.when).all()
        else:
            other_emails = {}

        return {
            'group': group,
            'emails': session.query(Email).filter(Email.model == 'Group',
                                                  Email.fk_id == id).order_by(Email.when).all(),
            'other_emails': other_emails,
            'changes': session.query(Tracking).filter(or_(
                Tracking.links.like('%group({})%'.format(id)),
                and_(Tracking.model == 'Group', Tracking.fk_id == id))).order_by(Tracking.when).all(),
            'pageviews': session.query(PageViewTracking).filter(PageViewTracking.which == repr(group)
                                                                ).order_by(PageViewTracking.when).all(),
        }

    @csrf_protected
    def delete(self, session, id, confirmed=None):
        group = session.group(id)
        if group.badges - group.unregistered_badges and not confirmed:
            raise HTTPRedirect('deletion_confirmation?id={}', id)
        else:
            for attendee in group.attendees:
                session.delete(attendee)
            session.delete(group)
            raise HTTPRedirect('index?message={}', 'Group deleted')

    def deletion_confirmation(self, session, id):
        return {'group': session.group(id)}

    @csrf_protected
    def assign_leader(self, session, group_id, attendee_id):
        group = session.group(group_id)
        attendee = session.attendee(attendee_id)
        if attendee not in group.attendees:
            raise HTTPRedirect('form?id={}&message={}', group_id, 'That attendee has been removed from the group')
        else:
            group.leader_id = attendee_id
            raise HTTPRedirect('form?id={}&message={}', group_id, 'Group leader set')

    def checklist_info(self, session, message='', event_id=None, **params):
        guest = session.guest_group(params)
        if not session.admin_can_see_guest_group(guest):
            raise HTTPRedirect('index?message={}', 'You cannot view {} groups'.format(guest.group_type_label.lower()))

        if cherrypy.request.method == 'POST':
            if event_id:
                guest.event_id = event_id
            message = check(guest)
            if not message:
                for field in ['estimated_loadin_minutes', 'estimated_performance_minutes']:
                    if field in params:
                        field_name = "load-in" if field == 'estimated_loadin_minutes' else 'performance'
                        if not params.get(field):
                            message = "Please enter more than 0 estimated {} minutes".format(field_name)
                        elif not str(params.get(field, '')).isdigit():
                            message = "Please enter a whole number for estimated {} minutes".format(field_name)
            if not message:
                raise HTTPRedirect('index?message={}{}', guest.group.name, ' data uploaded')

        events = session.query(Event).filter_by(location=c.CONCERTS).order_by(Event.start_time).all()
        return {
            'guest': guest,
            'message': message,
            'events': [(event.id, event.name) for event in events]
        }
