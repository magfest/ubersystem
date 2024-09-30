import base64
import uuid
import cherrypy
from datetime import datetime, timedelta
from pockets.autolog import log

from uber.config import c
from uber.custom_tags import readable_join
from uber.decorators import all_renderable, ajax, requires_account, render
from uber.errors import HTTPRedirect
from uber.forms import load_forms
from uber.models import Attendee, LotteryApplication
from uber.tasks.email import send_email
from uber.utils import RegistrationCode, validate_model, get_age_from_birthday, normalize_email_legacy


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
            f'{c.EVENT_NAME} Lottery Room Group "{old_room_group_name}" Disbanded',
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
            application = LotteryApplication(attendee_id=attendee_id)

        forms_list = ["LotteryInfo"]
        forms = load_forms(params, application, forms_list)

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

        return {
            'id': application.id,
            'attendee_id': attendee_id,
            'forms': forms,
            'message': message,
            'application': application,
            'attendee': attendee,
        }

    @requires_account(Attendee)
    def index(self, session, attendee_id=None, message="", **params):
        if 'id' in params:
            application = session.lottery_application(params['id'])
        elif attendee_id:
            attendee = session.attendee(attendee_id)
            application = attendee.lottery_application
        else:
            raise HTTPRedirect(f'../preregistration/homepage')

        if not application:
            raise HTTPRedirect(f'start?attendee_id={attendee_id}')
        elif not application.terms_accepted:
            raise HTTPRedirect(f'terms?attendee_id={attendee_id}')
        elif application.entry_form_completed and not application.guarantee_policy_accepted:
            raise HTTPRedirect(f'guarantee_confirm?id={application.id}')

        forms_list = ["RoomLottery", "SuiteLottery"]
        if application.parent_application:
            forms = load_forms(params, application.parent_application, forms_list)
        else:
            forms = load_forms(params, application, forms_list)

        return {
            'id': application.id,
            'attendee_id': attendee_id,
            'homepage_account': session.get_attendee_account_by_attendee(application.attendee),
            'forms': forms,
            'message': message,
            'confirm': params.get('confirm', ''),
            'action': params.get('action', ''),
            'application': application
        }

    @requires_account(LotteryApplication)
    def enter_attendee_lottery(self, session, id=None, **params):
        application = session.lottery_application(id)
        application.is_staff_entry = False
        application.last_submitted = datetime.now()
        application.status = c.COMPLETE
        application.confirmation_num = ''
        session.add(application)
        raise HTTPRedirect('index?attendee_id={}&message={}',
                           application.attendee.id,
                           "Your staff lottery entry has been entered into the attendee lottery.")
    
    @requires_account(LotteryApplication)
    def withdraw_entry(self, session, id=None, **params):
        application = session.lottery_application(id)

        has_actually_entered = application.status == c.COMPLETE
        was_room_group = application.room_group_name
        old_room_group = application.parent_application

        if was_room_group:
            _disband_room_group(session, application)

        defaults = LotteryApplication().to_dict()
        for attr in defaults:
            if attr not in ['id', 'attendee_id', 'response_id']:
                setattr(application, attr, defaults.get(attr))

        application.confirmation_num = ''
        application.status = c.WITHDRAWN

        if old_room_group:
            body = render('emails/hotel/group_member_left.html', {
                'application': old_room_group, 'member': application}, encoding=None)
            send_email.delay(
                c.HOTEL_LOTTERY_EMAIL,
                old_room_group.attendee.email_to_address,
                f'{application.attendee.first_name} has left your {c.EVENT_NAME} Lottery Room Group',
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

            raise HTTPRedirect('../preregistration/homepage?message={}',
                            f"You have been removed from the hotel lottery.{' Your group has been disbanded.' if was_room_group else ''}")
        raise HTTPRedirect('../preregistration/homepage?message={}',
                            f"Your hotel lottery entry has been cancelled.")

    @requires_account(LotteryApplication)
    def room_lottery(self, session, id=None, message="", **params):
        application = session.lottery_application(id)
        forms_list = ["RoomLottery"]

        if application.parent_application:
            message = "You cannot edit your room group's application."
            raise HTTPRedirect(f'index?attendee_id={application.attendee.id}&messsage={message}')
        
        forms = load_forms(params, application, forms_list)

        if cherrypy.request.method == 'POST':
            for form in forms.values():
                form.populate_obj(application)

            application.current_step = 999
            application.last_submitted = datetime.now()
            update_group_members = application.update_group_members

            if application.status == c.COMPLETE and c.STAFF_HOTEL_LOTTERY_OPEN and application.qualifies_for_staff_lottery:
                application.is_staff_entry = True
            else:
                application.is_staff_entry = False

            session.commit()
            session.refresh(application)

            if not application.guarantee_policy_accepted:
                raise HTTPRedirect('guarantee_confirm?id={}', application.id)
            else:
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

                raise HTTPRedirect('index?attendee_id={}&confirm=room&action=updated',
                                   application.attendee.id)

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
            message = "You cannot edit your room group's application."
            raise HTTPRedirect(f'index?attendee_id={application.attendee.id}&messsage={message}')

        forms = load_forms(params, application, forms_list)

        if cherrypy.request.method == 'POST':
            for form in forms.values():
                form.populate_obj(application)

            application.current_step = 999
            application.last_submitted = datetime.now()
            update_group_members = application.update_group_members

            if application.status == c.COMPLETE and c.STAFF_HOTEL_LOTTERY_OPEN and application.qualifies_for_staff_lottery:
                application.is_staff_entry = True
            else:
                application.is_staff_entry = False

            session.commit()
            session.refresh(application)

            if not application.guarantee_policy_accepted:
                raise HTTPRedirect('guarantee_confirm?id={}', application.id)
            else:
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

                raise HTTPRedirect('index?attendee_id={}&confirm=suite&action=updated',
                                   application.attendee.id)

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
        forms = load_forms(params, application, form_list, get_optional=False)

        all_errors = validate_model(forms, application, LotteryApplication(**application.to_dict()))
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
        forms = load_forms(params, application, forms_list)

        if cherrypy.request.method == 'POST':
            for form in forms.values():
                form.populate_obj(application)
            application.last_submitted = datetime.now()
            application.status = c.COMPLETE
            if c.STAFF_HOTEL_LOTTERY_OPEN and application.qualifies_for_staff_lottery:
                application.is_staff_entry = True

            session.commit()
            session.refresh(application)

            room_or_suite = "suite" if application.entry_type == c.SUITE_ENTRY else "room"
            body = render('emails/hotel/hotel_lottery_entry.html', {
                'application': application,
                'new_conf': False,
                'action_str': f"entering the {application.entry_type_label.lower()} lottery"}, encoding=None)
            send_email.delay(
                c.HOTEL_LOTTERY_EMAIL,
                application.attendee.email_to_address,
                c.EVENT_NAME_AND_YEAR + f' {application.entry_type_label} Lottery Confirmation',
                body,
                format='html',
                model=application.to_dict('id'))

            raise HTTPRedirect('index?attendee_id={}&confirm={}&action=confirmation',
                               application.attendee.id,
                               room_or_suite)
        return {
                'id': application.id,
                'homepage_account': session.get_attendee_account_by_attendee(application.attendee),
                'forms': forms,
                'message': message,
                'application': application,
            }

    @requires_account(LotteryApplication)
    def room_group(self, session, id=None, message="", **params):
        application = session.lottery_application(id)

        forms_list = ["LotteryRoomGroup"]
        forms = load_forms(params, application, forms_list)

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
            f'Removed From {c.EVENT_NAME} Lottery Room Group "{application.room_group_name}"',
            body,
            format='html',
            model=member.to_dict('id'))
        raise HTTPRedirect('room_group?id={}&message={}', application.id,
                           f"{member.attendee.full_name} has been removed from your room group.")
    
    @requires_account(LotteryApplication)
    def delete_group(self, session, id=None, message="", **params):
        application = session.lottery_application(id)
        old_room_group_name = application.room_group_name
        _disband_room_group(session, application)

        application.confirmation_num = ''

        raise HTTPRedirect('index?attendee_id={}&message={}', application.attendee.id,
                           f"{old_room_group_name} has been disbanded.")

    @ajax
    def room_group_search(self, session, member_id, **params):
        application = session.lottery_application(member_id)

        invite_code, leader_email = params.get('confirmation_num'), params.get('leader_email')
        errors = []
        if not invite_code:
            errors.append("a group confirmation number")
        if not leader_email:
            errors.append("the room group leader's email address")
        if errors:
            return {'error': f"Please enter {readable_join(errors)}."}

        #room_group = session.lookup_registration_code(invite_code, LotteryApplication)
        room_group = session.query(LotteryApplication).filter_by(confirmation_num=invite_code).first()

        if not room_group or room_group.attendee.normalized_email != normalize_email_legacy(leader_email):
            return {'error': "No room group found. Please check the confirmation number and leader email address."}

        if room_group.is_staff_entry and (not c.STAFF_HOTEL_LOTTERY_OPEN or not application.qualifies_for_staff_lottery):
            return {'error': "No valid room group found. Please check the confirmation number and leader email address."}

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
            elif application.group_members:
                message = "Please disband your own group before joining another group."
            if not message:
                room_group = session.lottery_application(params.get('room_group_id'))
                if len(room_group.group_members) == 3:
                    message = "This room group is full."
                elif room_group.is_staff_entry and (not c.STAFF_HOTEL_LOTTERY_OPEN or not application.qualifies_for_staff_lottery):
                    message = "This room group is locked."

                if message:
                    raise HTTPRedirect('room_group?id={}&message={}', application.id, message)

                if application.entry_type != c.GROUP_ENTRY and application.status != c.COMPLETE:
                    # We can revert to a completed app if the attendee leaves the group,
                    # but it's too messy for incomplete apps, so we clear them instead
                    defaults = LotteryApplication().to_dict()
                    for attr in defaults:
                        if attr not in ['id', 'attendee_id', 'response_id',
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
                application.parent_application = room_group
                if application.is_staff_entry and not application.parent_application.is_staff_entry:
                    application.is_staff_entry = False
                elif application.parent_application.is_staff_entry:
                    application.is_staff_entry = True

                body = render('emails/hotel/group_member_joined.html', {
                    'application': room_group, 'member': application}, encoding=None)
                send_email.delay(
                    c.HOTEL_LOTTERY_EMAIL,
                    room_group.attendee.email_to_address,
                    f'{application.attendee.first_name} has joined your {c.EVENT_NAME} Lottery Room Group',
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

            body = render('emails/hotel/group_member_left.html', {
                'application': room_group, 'member': application}, encoding=None)
            send_email.delay(
                c.HOTEL_LOTTERY_EMAIL,
                room_group.attendee.email_to_address,
                f'{application.attendee.first_name} has left your {c.EVENT_NAME} Lottery Room Group',
                body,
                format='html',
                model=room_group.to_dict('id'))
            
            application = _reset_group_member(application)

            if application.status == c.WITHDRAWN:
                raise HTTPRedirect('../preregistration/homepage?message={}',
                                   f'You have left the room group "{room_group.room_group_name}" and been removed from the hotel lottery.')
            raise HTTPRedirect('index?attendee_id={}&message={}&confirm={}&action={}',
                               application.attendee.id,
                               f'Successfully left the room group "{room_group.room_group_name}".',
                               "suite" if application.entry_type == c.SUITE_ENTRY else "room",
                               're-entered')
