import base64
import json
import uuid
import cherrypy
import logging
from datetime import datetime, timedelta
from sqlalchemy.orm.exc import NoResultFound

from uber.config import c
from uber.custom_tags import readable_join
from uber.decorators import all_renderable, ajax, ajax_gettable, requires_account, render
from uber.errors import HTTPRedirect
from uber.forms import load_forms
from sqlalchemy import func
from uber.models import Attendee, LotteryApplication
from uber.models.hotel import HotelRoomInventory, InventoryPartitionBlock
from uber.tasks.email import send_email
from uber.utils import RegistrationCode, validate_model, get_age_from_birthday, normalize_email_legacy

log = logging.getLogger(__name__)


def _join_room_group(session, application, group_id):
    message, got_new_conf_num = '', None

    try:
        room_group = session.lottery_application(group_id)
    except NoResultFound:
        message = f"No {c.HOTEL_LOTTERY_GROUP_TERM.lower()} found!"
    else:
        if len(room_group.valid_group_members) == 3:
            message = f"This {c.HOTEL_LOTTERY_GROUP_TERM.lower()} is full."
        elif room_group.is_staff_entry and not application.qualifies_for_staff_lottery:
            message = f"You are not eligible to join this {c.HOTEL_LOTTERY_GROUP_TERM.lower()}."
        elif room_group.locked:
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
            'app': member, 'parent': application, 'old_room_group_name': old_room_group_name}, encoding=None)
        send_email.delay(
            c.HOTEL_LOTTERY_EMAIL,
            member.attendee.email_to_address,
            f'{c.EVENT_NAME} Lottery {c.HOTEL_LOTTERY_GROUP_TERM} "{old_room_group_name}" Disbanded',
            body,
            format='html',
            model=member.to_dict('id'))
    
    session.commit()


def _reset_group_member(application):
    if application.guarantee_policy_accepted and not application.finalized:
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
        application.attendee.hotel_eligible = True
    
    if application.status == c.COMPLETE and c.STAFF_HOTEL_LOTTERY_OPEN and application.qualifies_for_staff_lottery:
        application.is_staff_entry = True
    else:
        application.is_staff_entry = False

    application.parent_application = None
    application.confirmation_num = ''
    return application


def _clear_application(application, status=c.WITHDRAWN):
    application.attendee.hotel_eligible = True
    keep_attrs = [
        'id', 'attendee_id', 'response_id', 'legal_first_name', 'legal_last_name', 'cellphone']

    defaults = LotteryApplication().to_dict()
    for attr in defaults:
        if attr not in keep_attrs:
            setattr(application, attr, defaults.get(attr))
    application.status = status
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
        if attendee.lottery_application and not attendee.lottery_application.can_reenter:
            raise HTTPRedirect('index?attendee_id={}', attendee.id)

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
            if not attendee.lottery_application.can_reenter:
                raise HTTPRedirect('index?attendee_id={}', attendee.id)
        else:
            application = LotteryApplication()
            application.attendee = attendee

        forms_list = ["LotteryInfo"]
        forms = load_forms(params, application, forms_list, read_only=application.current_lottery_closed)

        if cherrypy.request.method == 'POST':
            for form in forms.values():
                form.populate_obj(application)
            session.add(application)
            if application.can_reenter:
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
        elif application.locked:
            pass
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
                                       read_only=application.locked)

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
        if application.locked:
            raise HTTPRedirect('index?id={}&message={}', application.id,
                               "You cannot edit your contact info at this time.")

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
            'app': application,
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
        application = _reset_group_member(application)
        session.add(application)
        if application.status == c.COMPLETE:
            body = render('emails/hotel/hotel_lottery_entry.html', {
                'app': application,
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

        has_actually_entered = application.status == c.COMPLETE or application.finalized
        was_room_group = application.room_group_name
        old_room_group = application.parent_application

        if was_room_group:
            _disband_room_group(session, application)

        _clear_application(application)

        if old_room_group:
            body = render('emails/hotel/group_member_left.html', {
                'app': old_room_group, 'member': application}, encoding=None)
            send_email.delay(
                c.HOTEL_LOTTERY_EMAIL,
                old_room_group.attendee.email_to_address,
                f'{application.attendee.first_name} has left your {c.EVENT_NAME} Lottery {c.HOTEL_LOTTERY_GROUP_TERM}',
                body,
                format='html',
                model=old_room_group.to_dict('id'))

        if has_actually_entered:
            body = render('emails/hotel/lottery_entry_cancelled.html', {
                'app': application},
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
        elif application.locked:
            raise HTTPRedirect('index?id={}&message={}', application.id,
                               "You cannot edit your lottery entry at this time.")

        forms = load_forms(params, application, forms_list, read_only=application.current_lottery_closed)

        if cherrypy.request.method == 'POST':
            for form in forms.values():
                form.populate_obj(application)

            update_group_members = application.update_group_members

            if application.status == c.COMPLETE and c.STAFF_HOTEL_LOTTERY_OPEN and application.qualifies_for_staff_lottery:
                application.is_staff_entry = True
            elif not application.can_edit:
                application.is_staff_entry = False

            application.current_step = 999
            session.commit()
            session.refresh(application)

            if not application.guarantee_policy_accepted:
                raise HTTPRedirect('guarantee_confirm?id={}', application.id)
            else:
                if application.status == c.PARTIAL:
                    application.status = c.COMPLETE
                application.last_submitted = datetime.now()

                body = render('emails/hotel/hotel_lottery_entry.html', {
                    'app': application,
                    'action_str': "updating your room lottery entry"}, encoding=None)
                send_email.delay(
                    c.HOTEL_LOTTERY_EMAIL,
                    application.attendee.email_to_address,
                    c.EVENT_NAME_AND_YEAR + f' Room Lottery Updated',
                    body,
                    format='html',
                    model=application.to_dict('id'))
                if update_group_members:
                    for member in application.valid_group_members:
                        body = render('emails/hotel/group_entry_updated.html', {
                            'app': member}, encoding=None)
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
        elif application.locked:
            raise HTTPRedirect('index?id={}&message={}', application.id,
                               "You cannot edit your lottery entry at this time.")

        forms = load_forms(params, application, forms_list, read_only=application.current_lottery_closed)

        if cherrypy.request.method == 'POST':
            for form in forms.values():
                form.populate_obj(application)

            update_group_members = application.update_group_members

            if application.status == c.COMPLETE and c.STAFF_HOTEL_LOTTERY_OPEN and application.qualifies_for_staff_lottery:
                application.is_staff_entry = True
            elif not application.can_edit:
                application.is_staff_entry = False

            application.current_step = 999
            session.commit()
            session.refresh(application)

            if not application.guarantee_policy_accepted:
                raise HTTPRedirect('guarantee_confirm?id={}', application.id)
            else:
                if application.status == c.PARTIAL:
                    application.status = c.COMPLETE
                application.last_submitted = datetime.now()

                body = render('emails/hotel/hotel_lottery_entry.html', {
                    'app': application,
                    'action_str': "updating your suite lottery entry"}, encoding=None)
                send_email.delay(
                    c.HOTEL_LOTTERY_EMAIL,
                    application.attendee.email_to_address,
                    c.EVENT_NAME_AND_YEAR + f' Suite Lottery Updated',
                    body,
                    format='html',
                    model=application.to_dict('id'))
                
                if update_group_members:
                    for member in application.valid_group_members:
                        body = render('emails/hotel/group_entry_updated.html', {
                            'app': member}, encoding=None)
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
        
        if application.locked:
            return {"error": "You cannot edit your lottery entry at this time."}

        if not form_list:
            form_list = ["LotteryInfo"]
        elif isinstance(form_list, str):
            form_list = [form_list]
        forms = load_forms(params, application, form_list)

        all_errors = validate_model(session, forms, application)
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

        if application.locked:
            raise HTTPRedirect('index?id={}&message={}', application.id,
                               "You cannot edit your lottery entry at this time.")

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
                'app': application,
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
                               f"You cannot switch from a {application.entry_type_label} to a room or suite entry.")
        elif application.locked:
            raise HTTPRedirect('index?id={}&message={}', application.id,
                               "You cannot edit your lottery entry at this time.")

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

        # Query pending outbound invites sent by this leader
        pending_invites = []
        if application.room_group_name and not application.parent_application:
            pending_invites = session.query(LotteryApplication).filter(
                LotteryApplication.invited_by_id == application.id,
                LotteryApplication.invite_status == c.INVITE_PENDING,
            ).all()

        return {
            'id': application.id,
            'homepage_account': session.get_attendee_account_by_attendee(application.attendee),
            'forms': forms,
            'message': message,
            'application': application,
            'pending_invites': pending_invites,
            'create': params.get('create'),
            'action': params.get('action', ''),
            'new_conf': True if params.get('new_conf', "False") != "False" else False,
        }
    
    @requires_account(LotteryApplication)
    def save_group(self, session, id=None, message="", **params):
        application = session.lottery_application(id)

        if application.locked:
            raise HTTPRedirect('room_group?id={}&message={}', application.id,
                               f"You cannot edit or create a {c.HOTEL_LOTTERY_GROUP_TERM.lower()} at this time.")

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
        if application.locked:
            raise HTTPRedirect('index?id={}&message={}', application.id,
                               "You cannot remove group members at this time.")

        member = session.lottery_application(member_id)
        if application.status == c.PROCESSED or application.finalized:
            member = _clear_application(member)
        else:
            member = _reset_group_member(member)
        session.commit()
        session.refresh(member)
        body = render('emails/hotel/removed_from_group.html', {
            'app': member, 'parent': application, 'group_disbanded': False}, encoding=None)
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
    def transfer_leadership(self, session, id=None, member_id=None, message="", **params):
        application = session.lottery_application(id)
        new_leader = session.lottery_application(member_id)

        if new_leader not in application.valid_group_members:
            raise HTTPRedirect('index?attendee_id={}&message={}', application.attendee.id,
                               f"{new_leader.attendee.full_name} is not a member of your {c.HOTEL_LOTTERY_GROUP_TERM.lower()}")
        elif application.locked:
            raise HTTPRedirect('index?id={}&message={}', application.id,
                               "You cannot transfer group leadership at this time.")

        leader_entry = application.to_dict()
        defaults = LotteryApplication().to_dict()

        for attr in ['earliest_checkin_date', 'latest_checkin_date', 'earliest_checkout_date', 'latest_checkout_date',
                     'hotel_preference', 'room_type_preference', 'wants_ada', 'ada_requests',
                     'room_opt_out', 'suite_type_preference', 'suite_terms_accepted', 'guarantee_policy_accepted',
                     'assigned_inventory_id', 'assigned_check_in_date',
                     'assigned_check_out_date', 'deposit_cutoff_date', 'lottery_name', 'booking_url', 'room_group_name',
                     'status', 'entry_type', 'current_step']:
            setattr(new_leader, attr, leader_entry.get(attr))
            setattr(application, attr, defaults.get(attr))

        all_group_members = application.group_members + [application]
        for member in all_group_members:
            if member != new_leader:
                member.parent_application_id = new_leader.id
                session.add(member)

        application.status = new_leader.status
        application.entry_type = c.GROUP_ENTRY
        new_leader.parent_application_id = None
        session.commit()

        for member in all_group_members:
            body = render('emails/hotel/group_new_leader.html', {
                    'app': member, 'old_leader': application, 'new_leader': new_leader}, encoding=None)
            send_email.delay(
                c.HOTEL_LOTTERY_EMAIL,
                member.email_to_address,
                f'{c.EVENT_NAME} Lottery {c.HOTEL_LOTTERY_GROUP_TERM} Leader Changed',
                body,
                format='html',
                model=member.to_dict('id'))
        
        raise HTTPRedirect('index?id={}&message={}', application.id,
                           f"Group leadership successfully transferred to {new_leader.attendee.full_name}.")


    @requires_account(LotteryApplication)
    def delete_group(self, session, id=None, message="", **params):
        application = session.lottery_application(id)
        if application.locked:
            raise HTTPRedirect('index?id={}&message={}', application.id,
                               f"You cannot disband your {c.HOTEL_LOTTERY_GROUP_TERM.lower()} at this time.")

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

        if not room_group or room_group.attendee.normalized_email != normalize_email_legacy(leader_email) or room_group.locked or \
                room_group.is_staff_entry and (not c.STAFF_HOTEL_LOTTERY_OPEN or not application.qualifies_for_staff_lottery):
            return {'error': f"No {c.HOTEL_LOTTERY_GROUP_TERM.lower()} found. Please check the confirmation number and email address, \
                    and make sure the group you're trying to join is valid, open, and not full."}

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

        if application.locked:
            raise HTTPRedirect('index?id={}&message={}', application.id,
                               f"You cannot join a {c.HOTEL_LOTTERY_GROUP_TERM.lower()} at this time.")
        got_new_conf_num = False

        if cherrypy.request.method == "POST":
            if not params.get('room_group_id'):
                message = "Group ID invalid!"
            elif application.valid_group_members or application.room_group_name:
                message = "Please disband your own group before joining another group."
            elif application.parent_application:
                message = f"You are already in a {c.HOTEL_LOTTERY_GROUP_TERM.lower()}."
            if not message:
                message, got_new_conf_num = _join_room_group(session, application, params.get('room_group_id'))
                
                if message:
                    raise HTTPRedirect('room_group?id={}&message={}', application.id, message)

                room_group = session.lottery_application(params.get('room_group_id'))
                
                session.commit()
                session.refresh(application)

                body = render('emails/hotel/group_member_joined.html', {
                    'app': room_group, 'member': application}, encoding=None)
                send_email.delay(
                    c.HOTEL_LOTTERY_EMAIL,
                    room_group.attendee.email_to_address,
                    f'{application.attendee.first_name} has joined your {c.EVENT_NAME} Lottery {c.HOTEL_LOTTERY_GROUP_TERM}',
                    body,
                    format='html',
                    model=room_group.to_dict('id'))
                
                body = render('emails/hotel/hotel_lottery_entry.html', {
                    'app': application,
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

        if application.locked:
            raise HTTPRedirect('index?id={}&message={}', application.id,
                               f"You cannot leave your {c.HOTEL_LOTTERY_GROUP_TERM.lower()} at this time.")

        if cherrypy.request.method == "POST":
            room_group = application.parent_application

            if room_group.status in [c.COMPLETE, c.PROCESSED, c.AWARDED, c.SECURED]:
                body = render('emails/hotel/group_member_left.html', {
                    'app': room_group, 'member': application}, encoding=None)
                send_email.delay(
                    c.HOTEL_LOTTERY_EMAIL,
                    room_group.attendee.email_to_address,
                    f'{application.attendee.first_name} has left your {c.EVENT_NAME} Lottery {c.HOTEL_LOTTERY_GROUP_TERM}',
                    body,
                    format='html',
                    model=room_group.to_dict('id'))
            
            if room_group.status == c.PROCESSED or room_group.finalized:
                application = _clear_application(application)
            else:
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
        if application.parent_application or application.valid_group_members:
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
        if application.parent_application or application.valid_group_members:
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

    def secure_room(self, session, id, message='', **params):
        application = session.lottery_application(id)

        if application.parent_application:
            raise HTTPRedirect('index?attendee_id={}&message={}', application.attendee.id,
                               f"Only the leader of your {c.HOTEL_LOTTERY_GROUP_TERM.lower()} may secure the room.")
        if application.status not in (c.AWARDED, c.SECURED):
            raise HTTPRedirect('index?attendee_id={}&message={}', application.attendee.id,
                               "Your entry does not have a room award to secure.")
        if not c.VAULT_ENABLED:
            raise HTTPRedirect('index?attendee_id={}&message={}', application.attendee.id,
                               "Credit card collection is not currently available.")

        return {
            'application': application,
            'message': message,
        }

    @ajax
    def create_vault_session(self, session, id):
        """Create a PCI Vault capture session and return the iframe URL."""
        application = session.lottery_application(id)

        if application.status not in (c.AWARDED, c.SECURED):
            return {'error': 'This entry is not in a state that can be secured.'}

        inventory_item = application.assigned_inventory
        vault_reference = inventory_item.vault_reference if inventory_item else f"hotel_{application.assigned_hotel_id}"

        from uber.vault import create_capture_session, get_capture_iframe_url
        capture = create_capture_session(
            reference=vault_reference,
            webhook_metadata={'application_id': application.id},
        )
        iframe_url = get_capture_iframe_url(
            endpoint_id=capture['unique_id'],
            secret=capture['secret'],
            reference=vault_reference,
        )
        return {'success': True, 'iframe_url': iframe_url}

    @ajax
    def save_card_token(self, session, id, token, last_four='', card_type='', **params):
        """Save just the card token without requiring address or changing status."""
        from pytz import UTC
        application = session.lottery_application(id)

        if application.status not in (c.AWARDED, c.SECURED):
            return {'error': 'This entry is not in a state that can be secured.'}
        if not token:
            return {'error': 'No card token received.'}

        application.cc_token = token
        application.cc_last_four = last_four
        application.cc_card_type = card_type
        application.cc_captured_at = datetime.now(UTC)

        session.add(application)
        session.commit()
        return {'success': True}

    @ajax
    def secure_room_callback(self, session, id, token, last_four='', card_type='', **params):
        from pytz import UTC
        application = session.lottery_application(id)

        if application.status not in (c.AWARDED, c.SECURED):
            return {'error': 'This entry is not in a state that can be secured.'}
        if not token:
            return {'error': 'No card token received.'}

        # Require billing address
        address1 = params.get('address1', '').strip()
        city = params.get('city', '').strip()
        region = params.get('region', '').strip()
        zip_code = params.get('zip_code', '').strip()
        country = params.get('country', '').strip()

        if not all([address1, city, region, zip_code, country]):
            return {'error': 'Please fill in all required billing address fields.'}

        application.cc_token = token
        application.cc_last_four = last_four
        application.cc_card_type = card_type
        application.cc_captured_at = datetime.now(UTC)
        application.status = c.SECURED

        application.address1 = address1
        application.address2 = params.get('address2', '').strip()
        application.city = city
        application.region = region
        application.zip_code = zip_code
        application.country = country
        application.hotel_rewards_number = params.get('hotel_rewards_number', '').strip()

        # Handle date choice: accept assigned dates or request waitlist
        from dateutil import parser as dateparser
        date_choice = params.get('date_choice', 'accept')
        if date_choice == 'waitlist':
            requested_ci = params.get('requested_checkin', '')
            requested_co = params.get('requested_checkout', '')
            try:
                if requested_ci:
                    new_ci = dateparser.parse(requested_ci).date()
                    if new_ci <= application.assigned_check_in_date:
                        application.earliest_checkin_date = new_ci
                if requested_co:
                    new_co = dateparser.parse(requested_co).date()
                    if new_co >= application.assigned_check_out_date:
                        application.latest_checkout_date = new_co
            except (ValueError, OverflowError):
                return {'error': 'Invalid date format.'}
        else:
            # Accept: set requested dates to match assigned — no waitlist
            application.earliest_checkin_date = application.assigned_check_in_date
            application.latest_checkout_date = application.assigned_check_out_date

        # Also secure all group members
        for member in application.group_members:
            member.status = c.SECURED
            session.add(member)

        session.add(application)
        session.commit()
        return {'success': True}

    @ajax_gettable
    def vault_webhook(self, session, **params):
        """Webhook called by PCI Vault after a card is captured.

        Updates card metadata from the webhook payload. Structure:
        {
          "metadata": {"application_id": "..."},
          "token_info": {
            "token": "...",
            "safe_data": "{\"card_holder\": ..., \"last_four\": ..., \"card_type\": ...}",
            "card_metadata": {"issuer": [{"brand": ..., "issuing_bank": ..., ...}]},
            ...
          }
        }
        """
        # Verify webhook secret
        import hmac
        webhook_secret = cherrypy.request.headers.get('X-PCIVault-Webhook-Secret', '')
        if not c.VAULT_WEBHOOK_SECRET or not hmac.compare_digest(webhook_secret, c.VAULT_WEBHOOK_SECRET):
            cherrypy.response.status = 403
            return {'error': 'Invalid webhook secret'}

        # Parse JSON body
        try:
            body = json.loads(cherrypy.request.body.read())
        except Exception:
            cherrypy.response.status = 400
            return {'error': 'Invalid JSON body'}

        metadata = body.get('metadata', {})
        application_id = metadata.get('application_id', '')
        token_info = body.get('token_info', {})
        token = token_info.get('token', '')

        if not token or not application_id:
            cherrypy.response.status = 400
            return {'error': 'Missing token or application_id'}

        application = session.query(LotteryApplication).get(application_id)
        if not application:
            cherrypy.response.status = 404
            return {'error': 'Application not found'}

        # Only update if the token matches what we have stored
        if application.cc_token != token:
            return {'success': True}

        # Parse safe_data (JSON string with card holder, last four, etc.)
        try:
            safe_data = json.loads(token_info.get('safe_data', '{}'))
        except (json.JSONDecodeError, TypeError):
            safe_data = {}

        if safe_data.get('last_four'):
            application.cc_last_four = safe_data['last_four']
        if safe_data.get('card_type'):
            application.cc_card_type = safe_data['card_type']
        if safe_data.get('card_holder'):
            application.cc_card_holder = safe_data['card_holder']
        if safe_data.get('expiry'):
            application.cc_card_expiry = safe_data['expiry']

        # Parse issuer metadata
        card_metadata = token_info.get('card_metadata', {})
        issuers = card_metadata.get('issuer', [])
        if issuers and isinstance(issuers, list):
            issuer = issuers[0]
            if issuer.get('brand'):
                application.cc_issuer_brand = issuer['brand']
            if issuer.get('issuing_bank'):
                application.cc_issuer_bank = issuer['issuing_bank']
            if issuer.get('country_name'):
                application.cc_issuer_country = issuer['country_name']
            if issuer.get('card_type'):
                application.cc_issuer_card_type = issuer['card_type']
            if issuer.get('card_level'):
                application.cc_issuer_card_level = issuer['card_level']

        session.add(application)
        session.commit()

        return {'success': True}

    def edit_room(self, session, id, message='', **params):
        application = session.lottery_application(id)

        if application.parent_application:
            raise HTTPRedirect('index?attendee_id={}&message={}', application.attendee.id,
                               f"Only the leader of your {c.HOTEL_LOTTERY_GROUP_TERM.lower()} may edit the room.")
        if application.status not in [c.AWARDED, c.SECURED]:
            raise HTTPRedirect('index?attendee_id={}&message={}', application.attendee.id,
                               "Your entry does not have a room award to edit.")

        if cherrypy.request.method == "POST":
            if application.export_locked:
                raise HTTPRedirect('edit_room?id={}&message={}', id,
                                   'Your room details have been exported to the hotel and cannot be changed. '
                                   'Please contact us for assistance.')

            from dateutil import parser as dateparser
            from datetime import timedelta as td

            new_check_in = params.get('assigned_check_in_date')
            new_check_out = params.get('assigned_check_out_date')
            special_requests = params.get('special_requests', '')

            # Availability check with partial confirmation + waitlist
            if new_check_in and new_check_out and application.assigned_inventory:
                new_ci = dateparser.parse(new_check_in).date()
                new_co = dateparser.parse(new_check_out).date()
                inv = application.assigned_inventory
                nq_map = inv.night_quantity_map

                # Compute partition-aware capacity
                part_id = application.partition_id
                if part_id:
                    pb = session.query(InventoryPartitionBlock).filter_by(
                        partition_id=part_id, inventory_id=inv.id).first()
                    partition_cap = pb.quantity if pb else 0
                else:
                    total_partitioned = session.query(
                        func.coalesce(func.sum(InventoryPartitionBlock.quantity), 0)
                    ).filter(InventoryPartitionBlock.inventory_id == str(inv.id)).scalar()

                available_nights = []
                unavailable_nights = []
                day = new_ci
                while day < new_co:
                    block_qty = nq_map.get(day, inv.quantity) if nq_map else inv.quantity
                    if part_id:
                        capacity = min(partition_cap, block_qty)
                    else:
                        capacity = max(0, block_qty - total_partitioned)

                    part_filter = (LotteryApplication.partition_id == part_id) if part_id else (LotteryApplication.partition_id == None)
                    assigned_count = session.query(LotteryApplication).filter(
                        LotteryApplication.assigned_inventory_id == application.assigned_inventory_id,
                        LotteryApplication.status.in_(c.HOTEL_LOTTERY_AWARD_STATUSES),
                        LotteryApplication.entry_type != c.GROUP_ENTRY,
                        LotteryApplication.id != application.id,
                        LotteryApplication.assigned_check_in_date <= day,
                        LotteryApplication.assigned_check_out_date > day,
                        part_filter,
                    ).count()
                    if assigned_count >= capacity:
                        unavailable_nights.append(day)
                    else:
                        available_nights.append(day)
                    day += td(days=1)

                # Determine the confirmed contiguous range (must include current assigned range)
                confirmed_ci = application.assigned_check_in_date
                confirmed_co = application.assigned_check_out_date

                # Extend check-in earlier if those nights are available
                if new_ci < confirmed_ci:
                    d = confirmed_ci - td(days=1)
                    while d >= new_ci and d in available_nights:
                        confirmed_ci = d
                        d -= td(days=1)

                # Extend check-out later if those nights are available
                if new_co > confirmed_co:
                    d = confirmed_co
                    while d < new_co and d in available_nights:
                        confirmed_co = d + td(days=1)
                        d += td(days=1)

                application.assigned_check_in_date = confirmed_ci
                application.assigned_check_out_date = confirmed_co

                # Set requested dates to the full desired range (for waitlist tracking)
                application.earliest_checkin_date = new_ci
                application.latest_checkout_date = new_co

                # Update group members' dates
                for member in application.group_members:
                    member.assigned_check_in_date = confirmed_ci
                    member.assigned_check_out_date = confirmed_co
                    session.add(member)

                # Build redirect message
                if unavailable_nights:
                    wl_strs = [d.strftime('%a %-m/%-d') for d in unavailable_nights]
                    message = (f"Confirmed: {confirmed_ci.strftime('%a %-m/%-d')} – "
                               f"{confirmed_co.strftime('%a %-m/%-d')}. "
                               f"Waitlisted: {', '.join(wl_strs)}. "
                               f"You'll be notified if availability opens up.")
                else:
                    message = 'Room details updated.'
            else:
                if new_check_in:
                    application.assigned_check_in_date = dateparser.parse(new_check_in).date()
                if new_check_out:
                    application.assigned_check_out_date = dateparser.parse(new_check_out).date()

            application.special_requests = special_requests
            application.hotel_rewards_number = params.get('hotel_rewards_number', '').strip()

            # Address fields
            application.address1 = params.get('address1', '').strip()
            application.address2 = params.get('address2', '').strip()
            application.city = params.get('city', '').strip()
            application.region = params.get('region', '').strip()
            application.zip_code = params.get('zip_code', '').strip()
            application.country = params.get('country', '').strip()

            session.add(application)
            session.commit()
            if not message:
                message = 'Room details updated.'
            raise HTTPRedirect('index?attendee_id={}&message={}', application.attendee.id, message)

        # Get room capacity for guest invite limit
        inventory_item = application.assigned_inventory
        max_guests = inventory_item.capacity - 1 if inventory_item else 3

        return {
            'application': application,
            'max_guests': max_guests,
            'vault_enabled': c.VAULT_ENABLED,
            'message': message,
        }

    def invite_room_guest(self, session, id, email='', **params):
        application = session.lottery_application(id)
        message = ''

        if application.parent_application:
            message = f"Only the leader of your {c.HOTEL_LOTTERY_GROUP_TERM.lower()} may invite guests."
        elif application.status not in [c.AWARDED, c.SECURED]:
            message = "Your entry does not have a room award."
        elif not email:
            message = "Please enter an email address."
        else:
            normalized = email.strip().lower()
            guest_attendee = session.query(Attendee).filter(
                func.lower(Attendee.email) == normalized
            ).first()

            if not guest_attendee:
                message = "No attendee found with that email address."
            elif guest_attendee.id == application.attendee_id:
                message = "You cannot invite yourself."
            else:
                guest_app = getattr(guest_attendee, 'lottery_application', None)

                if guest_app and guest_app.parent_application_id:
                    message = "That attendee is already in a room group."
                elif guest_app and guest_app.status in [c.AWARDED, c.SECURED] and not guest_app.parent_application:
                    message = "That attendee already has their own room award."
                else:
                    if not guest_app:
                        guest_app = LotteryApplication(
                            attendee_id=guest_attendee.id,
                            status=c.COMPLETE,
                            entry_type=c.GROUP_ENTRY,
                            legal_first_name=guest_attendee.legal_first_name,
                            legal_last_name=guest_attendee.legal_last_name,
                            cellphone=guest_attendee.cellphone,
                        )
                        session.add(guest_app)
                        session.flush()

                    inventory_item = application.assigned_inventory
                    max_guests = inventory_item.capacity - 1 if inventory_item else 3
                    if len(application.valid_group_members) >= max_guests:
                        message = "This room is at capacity."
                    else:
                        guest_app.parent_application_id = application.id
                        guest_app.status = application.status
                        session.add(guest_app)
                        session.commit()
                        raise HTTPRedirect('edit_room?id={}&message={}', id, 'Guest added to your room.')

        raise HTTPRedirect('edit_room?id={}&message={}', id, message)

    def remove_room_guest(self, session, id, member_id, **params):
        application = session.lottery_application(id)
        member = session.lottery_application(member_id)

        if member.parent_application_id != application.id:
            raise HTTPRedirect('edit_room?id={}&message={}', id, 'That attendee is not in your room group.')

        member.parent_application_id = None
        member.status = c.COMPLETE
        session.add(member)
        session.commit()
        raise HTTPRedirect('edit_room?id={}&message={}', id, 'Guest removed from your room.')

    @requires_account(Attendee)
    def send_room_invite(self, session, id, email='', **params):
        application = session.lottery_application(id)
        message = ''

        if application.parent_application:
            message = f"Only the leader of a {c.HOTEL_LOTTERY_GROUP_TERM.lower()} may send invites."
        elif not application.room_group_name:
            message = f"You must create a {c.HOTEL_LOTTERY_GROUP_TERM.lower()} before sending invites."
        else:
            inventory_item = application.assigned_inventory
            max_group = inventory_item.capacity - 1 if inventory_item else 3
            if len(application.valid_group_members) >= max_group:
                message = f"Your {c.HOTEL_LOTTERY_GROUP_TERM.lower()} is full."
            elif not email:
                message = "Please enter an email address."
            else:
                normalized = normalize_email_legacy(email)
                guest_attendee = session.query(Attendee).filter(
                    Attendee.normalized_email == normalized
                ).first()

                if not guest_attendee:
                    message = "No attendee found with that email address. Please check the address and try again."
                else:
                    guest_app = getattr(guest_attendee, 'lottery_application', None)
                    if not guest_app:
                        guest_app = LotteryApplication(
                            attendee_id=guest_attendee.id,
                            status=c.COMPLETE,
                            entry_type=c.GROUP_ENTRY,
                            legal_first_name=guest_attendee.legal_first_name,
                            legal_last_name=guest_attendee.legal_last_name,
                            cellphone=guest_attendee.cellphone,
                        )
                        session.add(guest_app)
                        session.flush()
                    if guest_app.id == application.id:
                        message = "You cannot invite yourself."
                    elif guest_app.parent_application_id:
                        message = f"That attendee is already in a {c.HOTEL_LOTTERY_GROUP_TERM.lower()}."
                    elif guest_app.invite_status == c.INVITE_PENDING:
                        message = "That attendee already has a pending invite."
                    else:
                        token = str(uuid.uuid4())
                        guest_app.invite_token = token
                        guest_app.invited_by_id = application.id
                        guest_app.invite_status = c.INVITE_PENDING
                        guest_app.invite_expires_at = datetime.now() + timedelta(days=7)
                        session.add(guest_app)
                        session.commit()

                        # Send invite email
                        from uber.decorators import render
                        body = render('emails/hotel/room_guest_invite.html', {
                            'app': guest_app,
                            'leader': application,
                            'token': token,
                        }, encoding=None)
                        send_email.delay(
                            c.HOTEL_LOTTERY_EMAIL,
                            guest_attendee.email_to_address,
                            f'{c.EVENT_NAME} Hotel {c.HOTEL_LOTTERY_GROUP_TERM} Invite from {application.group_leader_name}',
                            body,
                            format='html',
                            model=guest_app.to_dict('id'))

                        raise HTTPRedirect('room_group?id={}&message={}', id,
                                           f'Invite sent to {email}.')

        raise HTTPRedirect('room_group?id={}&message={}', id, message)

    @requires_account(Attendee)
    def accept_invite(self, session, token, attendee_id=None, **params):
        if not token:
            raise HTTPRedirect('../preregistration/homepage?message={}', 'Invalid invite link.')

        guest_app = session.query(LotteryApplication).filter_by(invite_token=token).first()
        if not guest_app:
            raise HTTPRedirect('../preregistration/homepage?message={}', 'Invite not found or already used.')

        if guest_app.invite_status != c.INVITE_PENDING:
            raise HTTPRedirect('../preregistration/homepage?message={}',
                               f'This invite has been {guest_app.invite_status_label.lower()}.')

        if guest_app.invite_expires_at and guest_app.invite_expires_at < datetime.now():
            guest_app.invite_status = c.INVITE_EXPIRED
            session.add(guest_app)
            session.commit()
            raise HTTPRedirect('../preregistration/homepage?message={}', 'This invite has expired.')

        leader_app = session.lottery_application(guest_app.invited_by_id)

        if cherrypy.request.method == 'POST':
            if guest_app.parent_application_id:
                raise HTTPRedirect('../preregistration/homepage?message={}',
                                   f'You are already in a {c.HOTEL_LOTTERY_GROUP_TERM.lower()}.')

            msg, _ = _join_room_group(session, guest_app, leader_app.id)
            if msg:
                raise HTTPRedirect('accept_invite?token={}&message={}', token, msg)

            guest_app.invite_status = c.INVITE_ACCEPTED
            guest_app.invite_token = ''
            session.add(guest_app)
            session.commit()
            raise HTTPRedirect('index?attendee_id={}&message={}', guest_app.attendee.id,
                               f'You have joined {leader_app.room_group_name}!')

        return {
            'guest_app': guest_app,
            'leader_app': leader_app,
            'token': token,
        }

    @requires_account(Attendee)
    def cancel_invite(self, session, id, invite_app_id, **params):
        application = session.lottery_application(id)
        invite_app = session.lottery_application(invite_app_id)

        if str(invite_app.invited_by_id) != str(application.id):
            raise HTTPRedirect('room_group?id={}&message={}', id, 'That invite does not belong to your group.')

        invite_app.invite_status = c.INVITE_CANCELLED
        invite_app.invite_token = ''
        invite_app.invited_by_id = None
        session.add(invite_app)
        session.commit()
        raise HTTPRedirect('room_group?id={}&message={}', id, 'Invite cancelled.')

