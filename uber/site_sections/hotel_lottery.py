import base64
import uuid
import cherrypy
from datetime import datetime, timedelta
from pockets.autolog import log
from sqlalchemy.orm.exc import NoResultFound

from uber.config import c
from uber.custom_tags import readable_join
from uber.decorators import all_renderable, ajax, requires_account, render
from uber.errors import HTTPRedirect
from uber.forms import load_forms
from uber.models import Attendee, LotteryApplication
from uber.tasks.email import send_email
from uber.utils import RegistrationCode, validate_model, get_age_from_birthday, normalize_email_legacy


def _join_room_group(session, application, group_id):
    message, got_new_conf_num = '', None

    try:
        room_group = session.lottery_application(group_id)
    except NoResultFound:
        message = f"No {c.HOTEL_LOTTERY_GROUP_TERM.lower()} found!"
    else:
        if len(room_group.group_members) == 3:
            message = f"This {c.HOTEL_LOTTERY_GROUP_TERM.lower()} is full."
        elif room_group.is_staff_entry and (not c.STAFF_HOTEL_LOTTERY_OPEN or not application.qualifies_for_staff_lottery):
            message = f"This {c.HOTEL_LOTTERY_GROUP_TERM.lower()} is locked."
    if message:
        return message, got_new_conf_num
    
    if application.entry_type != c.GROUP_ENTRY and application.status != c.COMPLETE:
        # We can revert to a completed app if the attendee leaves the group,
        # but it's too messy for incomplete apps, so we clear them instead
        defaults = LotteryApplication().to_dict()
        for attr in defaults:
            if attr not in ['id', 'attendee_id', 'response_id',
                            'legal_first_name', 'legal_last_name', 'cellphone',
                            'terms_accepted', 'data_policy_accepted',
                            'entry_started', 'entry_metadata']:
                setattr(application, attr, defaults.get(attr))
    elif application.entry_type != c.GROUP_ENTRY:
        application.confirmation_num = ''
        got_new_conf_num = True

    if not application.entry_started:
        application.entry_started = datetime.now()
        application.entry_metadata = {
            'ip_address': cherrypy.request.headers.get('X-Forwarded-For', cherrypy.request.remote.ip),
            'user_agent': cherrypy.request.headers.get('User-Agent', ''),
            'referer': cherrypy.request.headers.get('Referer', '')}

    application.status = c.COMPLETE
    application.entry_type = c.GROUP_ENTRY
    application.last_submitted = datetime.now()
    application.attendee.hotel_eligible = False
    application.parent_application = room_group
    if application.is_staff_entry and not application.parent_application.is_staff_entry:
        application.is_staff_entry = False
    elif application.parent_application.is_staff_entry:
        application.is_staff_entry = True

    return message, got_new_conf_num


def _disband_room_group(session, application):
    old_room_group_name = application.room_group_name
    application.room_group_name = ''
    application.invite_code = ''

    for member in application.group_members:
        member = _reset_group_member(member)
        session.add(member)
        session.commit()
        body = render('emails/hotel/removed_from_group.html', {
            'application': member, 'parent': application, 'old_room_group_name': old_room_group_name}, encoding=None)
        send_email.delay(
            c.HOTEL_LOTTERY_EMAIL,
            member.attendee.email_to_address,
            f'{c.EVENT_NAME} Lottery {c.HOTEL_LOTTERY_GROUP_TERM} "{old_room_group_name}" Disbanded',
            body,
            format='html',
            model=member.to_dict('id'))
    
    session.commit()


def _reset_group_member(application):
    if application.guarantee_policy_accepted:
        if application.suite_type_preference:
            application.entry_type = c.SUITE_ENTRY
        else:
            application.entry_type = c.ROOM_ENTRY
        application.last_submitted = datetime.now()
    else:
        application.entry_type = None
        application.status = c.WITHDRAWN
        application.terms_accepted = False
        application.data_policy_accepted = False
    
    if application.status == c.COMPLETE and c.STAFF_HOTEL_LOTTERY_OPEN and application.qualifies_for_staff_lottery:
        application.is_staff_entry = True
    else:
        application.is_staff_entry = False

    application.parent_application = None
    application.confirmation_num = ''
    return application


def _clear_application(application, status=c.WITHDRAWN):
    application.status = status
    application.attendee.hotel_eligible = True
    keep_attrs = [
        'id', 'attendee_id', 'response_id', 'legal_first_name', 'legal_last_name', 'cellphone']

    defaults = LotteryApplication().to_dict()
    for attr in defaults:
        if attr not in keep_attrs:
            setattr(application, attr, defaults.get(attr))
    return application


def _return_link(attendee_id):
    if c.ATTENDEE_ACCOUNTS_ENABLED:
        return "../preregistration/homepage?"
    else:
        return f"../preregistration/confirm?id={attendee_id}&"


@all_renderable(public=True)
class Root:
    @requires_account(Attendee)
    def start(self, session, attendee_id, message="", **params):
        attendee = session.attendee(attendee_id)
        return {
            'attendee': attendee,
            'message': message,
            'homepage_account': session.get_attendee_account_by_attendee(attendee),
        }

    @requires_account(Attendee)
    def terms(self, session, attendee_id, message="", **params):
        attendee = session.attendee(attendee_id)
        if attendee.lottery_application:
            application = attendee.lottery_application
        else:
            application = LotteryApplication()
            application.attendee = attendee

        forms_list = ["LotteryInfo"]
        forms = load_forms(params, application, forms_list, read_only=application.current_lottery_closed)

        if cherrypy.request.method == 'POST':
            for form in forms.values():
                form.populate_obj(application)
            session.add(application)
            application.status = c.PARTIAL
            session.commit()

            if params.get('group'):
                raise HTTPRedirect(f'room_group?id={application.id}')
            elif params.get('suite'):
                raise HTTPRedirect(f'suite_lottery?id={application.id}')
            elif params.get('room'):
                raise HTTPRedirect(f'room_lottery?id={application.id}')
            else:
                group_id = params.get('group_id')
                if application.status not in [c.PARTIAL, c.WITHDRAWN]:
                    message = "Application status has changed, please view your new options below."
                elif not group_id:
                    message = f'Group lookup failed. Please use the "Join {c.HOTEL_LOTTERY_GROUP_TERM}" button to try again.'
                else:
                    message, _ = _join_room_group(session, application, group_id)

                if not message:
                    room_group = session.lottery_application(group_id)
                    message = f'Successfully joined {c.HOTEL_LOTTERY_GROUP_TERM.lower()} "{room_group.room_group_name}"!'
                raise HTTPRedirect(f'index?id={application.id}&message={message}')

        return {
            'id': application.id,
            'attendee_id': attendee_id,
            'forms': forms,
            'message': message,
            'application': application,
            'attendee': attendee,
        }

    @requires_account([Attendee, LotteryApplication])
    def index(self, session, attendee_id=None, message="", **params):
        if 'id' in params:
            application = session.lottery_application(params['id'])
            attendee_id = application.attendee.id
        elif attendee_id:
            attendee = session.attendee(attendee_id)
            application = attendee.lottery_application
        elif c.ATTENDEE_ACCOUNTS_ENABLED:
            raise HTTPRedirect(f'../preregistration/homepage')
        else:
            raise HTTPRedirect(f'../landing/index')

        if not application:
            raise HTTPRedirect(f'start?attendee_id={attendee_id}')
        elif not application.terms_accepted:
            raise HTTPRedirect(f'terms?attendee_id={attendee_id}')
        elif application.entry_form_completed and not application.guarantee_policy_accepted:
            raise HTTPRedirect(f'guarantee_confirm?id={application.id}')

        forms_list = ["RoomLottery", "SuiteLottery"]
        if application.parent_application:
            forms = load_forms(params, application.parent_application, forms_list, read_only=True)
        else:
            forms = load_forms(params, application, forms_list, read_only=True)

        contact_form_dict = load_forms(params, application, ["LotteryInfo"],
                                       read_only=application.current_lottery_closed)

        return {
            'id': application.id,
            'attendee_id': attendee_id,
            'homepage_account': session.get_attendee_account_by_attendee(application.attendee),
            'forms': forms,
            'lottery_info': contact_form_dict['lottery_info'],
            'message': message,
            'confirm': params.get('confirm', ''),
            'action': params.get('action', ''),
            'application': application
        }
    
    @requires_account(LotteryApplication)
    def update_contact_info(self, session, id, **params):
        application = session.lottery_application(id)
        forms = load_forms(params, application, ["LotteryInfo"])
        for form in forms.values():
            form.populate_obj(application)
        raise HTTPRedirect('index?id={}&message={}',
                           application.id,
                           "Contact information updated!")

    @requires_account(LotteryApplication)
    def enter_attendee_lottery(self, session, id=None, **params):
        application = session.lottery_application(id)
        application.is_staff_entry = False
        application.last_submitted = datetime.now()
        application.status = c.COMPLETE
        application.confirmation_num = ''
        application.attendee.hotel_eligible = False
        session.add(application)
        
        body = render('emails/hotel/hotel_lottery_entry.html', {
            'application': application,
            'maybe_swapped': False,
            'new_conf': False,
            'action_str': f"entering the {application.entry_type_label.lower()} attendee lottery"}, encoding=None)
        send_email.delay(
            c.HOTEL_LOTTERY_EMAIL,
            application.attendee.email_to_address,
            c.EVENT_NAME_AND_YEAR + f' {application.entry_type_label} Lottery Confirmation',
            body,
            format='html',
            model=application.to_dict('id'))

        raise HTTPRedirect('index?id={}&message={}',
                           application.id,
                           "Your staff lottery entry has been entered into the attendee lottery.")

    @requires_account(LotteryApplication)
    def reenter_lottery(self, session, id=None, **params):
        application = session.lottery_application(id)
        _reset_group_member(application)
        session.add(application)
        if application.status == c.COMPLETE:
            body = render('emails/hotel/hotel_lottery_entry.html', {
                'application': application,
                'maybe_swapped': False,
                'new_conf': False,
                'action_str': f"re-entering the {application.entry_type_label.lower()} lottery"}, encoding=None)
            send_email.delay(
                c.HOTEL_LOTTERY_EMAIL,
                application.attendee.email_to_address,
                c.EVENT_NAME_AND_YEAR + f' {application.entry_type_label} Lottery Confirmation',
                body,
                format='html',
                model=application.to_dict('id'))
        else:
            raise HTTPRedirect('start?attendee_id={}&message={}',
                               application.attendee.id,
                               "Your lottery entry has been reset and you may now re-enter.")

    @requires_account(LotteryApplication)
    def withdraw_entry(self, session, id=None, **params):
        application = session.lottery_application(id)

        has_actually_entered = application.status == c.COMPLETE
        was_room_group = application.room_group_name
        old_room_group = application.parent_application

        if was_room_group:
            _disband_room_group(session, application)

        _clear_application(application)

        if old_room_group:
            body = render('emails/hotel/group_member_left.html', {
                'application': old_room_group, 'member': application}, encoding=None)
            send_email.delay(
                c.HOTEL_LOTTERY_EMAIL,
                old_room_group.attendee.email_to_address,
                f'{application.attendee.first_name} has left your {c.EVENT_NAME} Lottery {c.HOTEL_LOTTERY_GROUP_TERM}',
                body,
                format='html',
                model=old_room_group.to_dict('id'))

        if has_actually_entered:
            body = render('emails/hotel/lottery_entry_cancelled.html', {
                'application': application},
                encoding=None)
            send_email.delay(
                c.HOTEL_LOTTERY_EMAIL,
                application.attendee.email_to_address,
                c.EVENT_NAME_AND_YEAR + f' Lottery Entry Cancelled',
                body,
                format='html',
                model=application.to_dict('id'))

            raise HTTPRedirect('{}message={}'.format(_return_link(application.attendee.id),
                            f"You have been removed from the hotel lottery.{' Your group has been disbanded.' if was_room_group else ''}"))
        raise HTTPRedirect('{}message={}'.format(_return_link(application.attendee.id),
                            f"Your hotel lottery entry has been cancelled."))

    @requires_account(LotteryApplication)
    def room_lottery(self, session, id=None, message="", **params):
        application = session.lottery_application(id)
        forms_list = ["RoomLottery"] + (["SuiteLottery"] if application.current_lottery_closed else [])

        if application.parent_application:
            message = f"You cannot edit your {c.HOTEL_LOTTERY_GROUP_TERM.lower()}'s application."
            raise HTTPRedirect(f'index?id={application.id}&messsage={message}')

        forms = load_forms(params, application, forms_list, read_only=application.current_lottery_closed)

        if cherrypy.request.method == 'POST':
            for form in forms.values():
                form.populate_obj(application)

            update_group_members = application.update_group_members

            if application.status == c.COMPLETE and c.STAFF_HOTEL_LOTTERY_OPEN and application.qualifies_for_staff_lottery:
                application.is_staff_entry = True
            else:
                application.is_staff_entry = False

            application.current_step = 999
            session.commit()
            session.refresh(application)

            if not application.guarantee_policy_accepted:
                raise HTTPRedirect('guarantee_confirm?id={}', application.id)
            else:
                application.last_submitted = datetime.now()

                body = render('emails/hotel/hotel_lottery_entry.html', {
                    'application': application,
                    'action_str': "updating your room lottery entry"}, encoding=None)
                send_email.delay(
                    c.HOTEL_LOTTERY_EMAIL,
                    application.attendee.email_to_address,
                    c.EVENT_NAME_AND_YEAR + f' Room Lottery Updated',
                    body,
                    format='html',
                    model=application.to_dict('id'))
                if update_group_members:
                    for member in application.group_members:
                        body = render('emails/hotel/group_entry_updated.html', {
                            'application': member}, encoding=None)
                        send_email.delay(
                            c.HOTEL_LOTTERY_EMAIL,
                            member.attendee.email_to_address,
                            c.EVENT_NAME_AND_YEAR + f' Room Lottery Updated',
                            body,
                            format='html',
                            model=application.to_dict('id'))

                raise HTTPRedirect('index?id={}&confirm=room&action=updated',
                                   application.id)

        return {
            'id': application.id,
            'homepage_account': session.get_attendee_account_by_attendee(application.attendee),
            'forms': forms,
            'message': message,
            'application': application,
        }
    
    @requires_account(LotteryApplication)
    def suite_lottery(self, session, id=None, message="", **params):
        application = session.lottery_application(id)
        forms_list = ["SuiteLottery"]

        if application.parent_application:
            message = f"You cannot edit your {c.HOTEL_LOTTERY_GROUP_TERM.lower()}'s application."
            raise HTTPRedirect(f'index?id={application.id}&messsage={message}')

        forms = load_forms(params, application, forms_list, read_only=application.current_lottery_closed)

        if cherrypy.request.method == 'POST':
            for form in forms.values():
                form.populate_obj(application)

            update_group_members = application.update_group_members

            if application.status == c.COMPLETE and c.STAFF_HOTEL_LOTTERY_OPEN and application.qualifies_for_staff_lottery:
                application.is_staff_entry = True
            else:
                application.is_staff_entry = False

            application.current_step = 999
            session.commit()
            session.refresh(application)

            if not application.guarantee_policy_accepted:
                raise HTTPRedirect('guarantee_confirm?id={}', application.id)
            else:
                application.last_submitted = datetime.now()

                body = render('emails/hotel/hotel_lottery_entry.html', {
                    'application': application,
                    'action_str': "updating your suite lottery entry"}, encoding=None)
                send_email.delay(
                    c.HOTEL_LOTTERY_EMAIL,
                    application.attendee.email_to_address,
                    c.EVENT_NAME_AND_YEAR + f' Suite Lottery Updated',
                    body,
                    format='html',
                    model=application.to_dict('id'))
                
                if update_group_members:
                    for member in application.group_members:
                        body = render('emails/hotel/group_entry_updated.html', {
                            'application': member}, encoding=None)
                        send_email.delay(
                            c.HOTEL_LOTTERY_EMAIL,
                            member.attendee.email_to_address,
                            c.EVENT_NAME_AND_YEAR + f' Suite Lottery Updated',
                            body,
                            format='html',
                            model=application.to_dict('id'))

                raise HTTPRedirect('index?id={}&confirm=suite&action=updated',
                                   application.id)

        return {
            'id': application.id,
            'homepage_account': session.get_attendee_account_by_attendee(application.attendee),
            'forms': forms,
            'message': message,
            'application': application,
            'read_only': False,
        }

    @ajax
    def validate_hotel_lottery(self, session, attendee_id=None, form_list=[], **params):
        if params.get('id') in [None, '', 'None']:
            if attendee_id:
                attendee = session.attendee(attendee_id)
                application = attendee.lottery_application or LotteryApplication()
            else:
                return {"error": "There was an issue with the form. Please refresh and try again."}
        else:
            application = session.lottery_application(params.get('id'))
            attendee = application.attendee

        if not form_list:
            form_list = ["LotteryInfo"]
        elif isinstance(form_list, str):
            form_list = [form_list]
        forms = load_forms(params, application, form_list)

        all_errors = validate_model(forms, application)
        check_date = params.get('earliest_suite_checkin_date', params.get('earliest_room_checkin_date', ''))
        if attendee.birthdate and check_date and get_age_from_birthday(attendee.birthdate,
                                                                       check_date) < 21:
            all_errors[''].append("You must be at least 21 on your preferred check-in date.")
        if all_errors:
            return {"error": all_errors}
        current_step = params.get('current_step', 0)

        if current_step:
            # This is unusual for a validation function, but we want to save at each step of the form
            for form in forms.values():
                form.populate_obj(application)

            if not application.entry_started:
                application.entry_started = datetime.now()
                application.entry_metadata = {
                    'ip_address': cherrypy.request.headers.get('X-Forwarded-For', cherrypy.request.remote.ip),
                    'user_agent': cherrypy.request.headers.get('User-Agent', ''),
                    'referer': cherrypy.request.headers.get('Referer', '')}

            session.commit()

        return {"success": True, "step_completed": params.get('current_step', 0)}

    @requires_account(LotteryApplication)
    def guarantee_confirm(self, session, id=None, message="", **params):
        application = session.lottery_application(id)
        forms_list = ["LotteryConfirm"]
        forms = load_forms(params, application, forms_list, read_only=application.current_lottery_closed)

        if cherrypy.request.method == 'POST':
            for form in forms.values():
                form.populate_obj(application)

            maybe_swapped = application.last_submitted != None
            application.last_submitted = datetime.now()
            application.status = c.COMPLETE
            application.attendee.hotel_eligible = False

            if c.STAFF_HOTEL_LOTTERY_OPEN and application.qualifies_for_staff_lottery:
                application.is_staff_entry = True

            session.commit()
            session.refresh(application)

            room_or_suite = "suite" if application.entry_type == c.SUITE_ENTRY else "room"
            body = render('emails/hotel/hotel_lottery_entry.html', {
                'application': application,
                'maybe_swapped': maybe_swapped,
                'new_conf': False,
                'action_str': f"entering the {application.entry_type_label.lower()} lottery"}, encoding=None)
            send_email.delay(
                c.HOTEL_LOTTERY_EMAIL,
                application.attendee.email_to_address,
                c.EVENT_NAME_AND_YEAR + f' {application.entry_type_label} Lottery Confirmation',
                body,
                format='html',
                model=application.to_dict('id'))

            raise HTTPRedirect('index?id={}&confirm={}&action=confirmation',
                               application.id,
                               room_or_suite)
        return {
                'id': application.id,
                'homepage_account': session.get_attendee_account_by_attendee(application.attendee),
                'forms': forms,
                'message': message,
                'application': application,
            }

    @requires_account(LotteryApplication)
    def switch_entry_type(self, session, id, **params):
        application = session.lottery_application(id)

        if application.entry_type not in [c.ROOM_ENTRY, c.SUITE_ENTRY]:
            raise HTTPRedirect('index?id={}&message={}', application.id,
                               f"You cannot switch from a {application.entry_level} to a room or suite entry.")

        application.status = c.PARTIAL
        application.current_step = 0
        application.guarantee_policy_accepted = False

        if application.entry_type == c.ROOM_ENTRY:
            application.entry_type = c.SUITE_ENTRY
            if 'suite_ada_info' not in c.HOTEL_LOTTERY_FORM_STEPS:
                application.wants_ada = False
                application.ada_requests = ''
        elif application.entry_type == c.SUITE_ENTRY:
            application.entry_type = c.ROOM_ENTRY
            application.suite_terms_accepted = False
            application.room_opt_out = False
            application.suite_type_preference = ''
        raise HTTPRedirect('{}_lottery?id={}&message={}', 'room' if application.entry_type == c.ROOM_ENTRY else 'suite',
                           application.id,
                           "Entry type switched! Please make sure to carefully review and confirm your new entry.")
        

    @requires_account(LotteryApplication)
    def room_group(self, session, id=None, message="", **params):
        application = session.lottery_application(id)

        forms_list = ["LotteryRoomGroup"]
        forms = load_forms(params, application, forms_list, read_only=application.current_lottery_closed)

        if cherrypy.request.method == 'POST':
            pass

        return {
            'id': application.id,
            'homepage_account': session.get_attendee_account_by_attendee(application.attendee),
            'forms': forms,
            'message': message,
            'application': application,
            'create': params.get('create'),
            'action': params.get('action', ''),
            'new_conf': True if params.get('new_conf', "False") != "False" else False,
        }
    
    @requires_account(LotteryApplication)
    def save_group(self, session, id=None, message="", **params):
        application = session.lottery_application(id)

        forms_list = ["LotteryRoomGroup"]
        forms = load_forms(params, application, forms_list)

        if cherrypy.request.method == 'POST':
            if not application.room_group_name or not application.invite_code:
                action = "created"
                application.invite_code = RegistrationCode.generate_random_code(LotteryApplication.invite_code)
            else:
                action = "updated"
            
            for form in forms.values():
                form.populate_obj(application)
                application.last_submitted = datetime.now()
                raise HTTPRedirect('room_group?id={}&action={}', application.id, action)

    @requires_account(LotteryApplication)
    def new_invite_code(self, session, id=None, message="", **params):
        # Unused for now but we would like to move to this in the future
        application = session.lottery_application(id)
        application.invite_code = RegistrationCode.generate_random_code(LotteryApplication.invite_code)
        raise HTTPRedirect('room_group?id={}&message={}', application.id,
                           f"New invite code generated. Your new code is {application.invite_code}.")
    
    @requires_account(LotteryApplication)
    def remove_group_member(self, session, id=None, member_id=None, message="", **params):
        application = session.lottery_application(id)
        member = session.lottery_application(member_id)
        member = _reset_group_member(member)
        session.commit()
        session.refresh(member)
        body = render('emails/hotel/removed_from_group.html', {
            'application': member, 'parent': application, 'group_disbanded': False}, encoding=None)
        send_email.delay(
            c.HOTEL_LOTTERY_EMAIL,
            member.attendee.email_to_address,
            f'Removed From {c.EVENT_NAME} Lottery {c.HOTEL_LOTTERY_GROUP_TERM} "{application.room_group_name}"',
            body,
            format='html',
            model=member.to_dict('id'))
        raise HTTPRedirect('room_group?id={}&message={}', application.id,
                           f"{member.attendee.full_name} has been removed from your {c.HOTEL_LOTTERY_GROUP_TERM.lower()}.")
    
    @requires_account(LotteryApplication)
    def delete_group(self, session, id=None, message="", **params):
        application = session.lottery_application(id)
        old_room_group_name = application.room_group_name
        _disband_room_group(session, application)

        application.confirmation_num = ''

        raise HTTPRedirect('index?id={}&message={}', application.id,
                           f"{old_room_group_name} has been disbanded.")

    @ajax
    def room_group_search(self, session, member_id, **params):
        application = session.lottery_application(member_id)

        invite_code, leader_email = params.get('confirmation_num'), params.get('leader_email')
        errors = []
        if not invite_code:
            errors.append("a group confirmation number")
        if not leader_email:
            errors.append(f"the {c.HOTEL_LOTTERY_GROUP_TERM.lower()} leader's email address")
        if errors:
            return {'error': f"Please enter {readable_join(errors)}."}

        #room_group = session.lookup_registration_code(invite_code, LotteryApplication)
        room_group = session.query(LotteryApplication).filter(
            LotteryApplication.confirmation_num == invite_code,
            LotteryApplication.room_group_name != '').first()

        if not room_group or room_group.attendee.normalized_email != normalize_email_legacy(leader_email) or \
                room_group.is_staff_entry and (not c.STAFF_HOTEL_LOTTERY_OPEN or not application.qualifies_for_staff_lottery):
            return {'error': f"No {c.HOTEL_LOTTERY_GROUP_TERM.lower()} found. Please check the confirmation number and leader email address, \
                    and make sure the application you're trying to join is a valid {c.HOTEL_LOTTERY_GROUP_TERM.lower()}."}

        if room_group.finalized:
            return {'error': f"No valid {c.HOTEL_LOTTERY_GROUP_TERM.lower()} found."}

        return {
            'success': True,
            'invite_code': invite_code,
            'room_group_name': room_group.room_group_name,
            'leader_name': room_group.group_leader_name,
            'room_group_id': room_group.id
        }

    @requires_account(LotteryApplication)
    def join_group(self, session, id=None, message="", **params):
        application = session.lottery_application(id)
        got_new_conf_num = False

        if cherrypy.request.method == "POST":
            if not params.get('room_group_id'):
                message = "Group ID invalid!"
            elif application.group_members or application.room_group_name:
                message = "Please disband your own group before joining another group."
            if not message:
                message, got_new_conf_num = _join_room_group(session, application, params.get('room_group_id'))
                
                if message:
                    raise HTTPRedirect('room_group?id={}&message={}', application.id, message)

                room_group = session.lottery_application(params.get('room_group_id'))
                
                session.commit()
                session.refresh(application)

                body = render('emails/hotel/group_member_joined.html', {
                    'application': room_group, 'member': application}, encoding=None)
                send_email.delay(
                    c.HOTEL_LOTTERY_EMAIL,
                    room_group.attendee.email_to_address,
                    f'{application.attendee.first_name} has joined your {c.EVENT_NAME} Lottery {c.HOTEL_LOTTERY_GROUP_TERM}',
                    body,
                    format='html',
                    model=room_group.to_dict('id'))
                
                body = render('emails/hotel/hotel_lottery_entry.html', {
                    'application': application,
                    'new_conf': got_new_conf_num,
                    'action_str': f"entering the lottery as a roommate"}, encoding=None)
                send_email.delay(
                    c.HOTEL_LOTTERY_EMAIL,
                    application.attendee.email_to_address,
                    c.EVENT_NAME_AND_YEAR + f' {application.entry_type_label} Lottery Confirmation',
                    body,
                    format='html',
                    model=application.to_dict('id'))

                raise HTTPRedirect('room_group?id={}&action={}&new_conf={}', application.id, "joined", got_new_conf_num)
    
    @requires_account(LotteryApplication)
    def leave_group(self, session, id=None, message="", **params):
        application = session.lottery_application(id)

        if cherrypy.request.method == "POST":
            room_group = application.parent_application

            if room_group.status in [c.COMPLETE, c.PROCESSED, c.AWARDED, c.SECURED]:
                body = render('emails/hotel/group_member_left.html', {
                    'application': room_group, 'member': application}, encoding=None)
                send_email.delay(
                    c.HOTEL_LOTTERY_EMAIL,
                    room_group.attendee.email_to_address,
                    f'{application.attendee.first_name} has left your {c.EVENT_NAME} Lottery {c.HOTEL_LOTTERY_GROUP_TERM}',
                    body,
                    format='html',
                    model=room_group.to_dict('id'))
            
            application = _reset_group_member(application)

            if application.status == c.WITHDRAWN:
                raise HTTPRedirect('{}message={}'.format(_return_link(application.attendee.id),
                                   f'You have left the {c.HOTEL_LOTTERY_GROUP_TERM.lower()} \
                                    "{room_group.room_group_name}" and been removed from the hotel lottery.'))
            raise HTTPRedirect('index?id={}&message={}&confirm={}&action={}',
                               application.id,
                               f'Successfully left the {c.HOTEL_LOTTERY_GROUP_TERM.lower()} "{room_group.room_group_name}".',
                               "suite" if application.entry_type == c.SUITE_ENTRY else "room",
                               're-entered')
        
    def confirm(self, session, id, message='', **params):
        application = session.lottery_application(id)
        if application.parent_application or application.group_members:
            you_str = f"Your {c.HOTEL_LOTTERY_GROUP_TERM.lower()}'s"
        else:
            you_str = "Your"

        if not application.status in [c.AWARDED, c.SECURED]:
            message = f"{you_str} entry does not have a room or suite award."
        if not application.booking_url:
            message = f"{you_str} entry is still being processed and the booking link is not available yet."

        if application.parent_application:
            message = f"Only the leader of your {c.HOTEL_LOTTERY_GROUP_TERM.lower()} may confirm or edit your room or suite award."
        
        if message:
            raise HTTPRedirect('index?id={}&message={}', id, message)
        raise HTTPRedirect(application.booking_url)
        
    def decline(self, session, id, message='', **params):
        application = session.lottery_application(id)
        if application.parent_application or application.group_members:
            you_str = f"Your {c.HOTEL_LOTTERY_GROUP_TERM.lower()}'s"
        else:
            you_str = "Your"

        if application.status == c.SECURED:
            message = "You cannot cancel a reservation that has already been confirmed with a credit card guarantee."
        elif application.status == c.CANCELLED:
            message = "This reservation has already been cancelled."
        elif application.status != c.AWARDED:
            message = f"{you_str} entry does not have a room or suite award."

        if application.parent_application:
            message = f"Only the leader of your {c.HOTEL_LOTTERY_GROUP_TERM.lower()} may decline your room or suite award."
        
        if message:
            raise HTTPRedirect('index?id={}&message={}', id, message)
        
        if cherrypy.request.method == "POST":
            room_type = 'suite' if application.assigned_suite_type else 'room'
            if 'confirm' not in params:
                message = f"Please check the box confirming that you want to give up {you_str.lower()} {room_type} award."
            else:
                _clear_application(application, status=c.CANCELLED)
                if application.group_members:
                    for group_member in application.group_members:
                        _clear_application(group_member, status=c.CANCELLED)
                        group_member.former_parent_id = application.id

                    message = f"You have declined your {c.HOTEL_LOTTERY_GROUP_TERM.lower()}'s {room_type} award. \
                        Your lottery entry has been cancelled and your {c.HOTEL_LOTTERY_GROUP_TERM.lower()} has been disbanded."
                else:
                    message = f"You have declined your {room_type} award and your lottery entry has been cancelled."
                raise HTTPRedirect('{}message={}'.format(_return_link(application.attendee.id), message))

        return {
            'application': application,
            'message': message,
        }

