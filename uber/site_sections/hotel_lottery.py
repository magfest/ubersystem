import base64
import uuid
import requests
import cherrypy
from collections import defaultdict
from datetime import datetime, timedelta
from dateutil import parser as dateparser
from pockets.autolog import log
from sqlalchemy import func
from sqlalchemy.sql.expression import literal

from uber.config import c
from uber.custom_tags import readable_join
from uber.decorators import all_renderable, ajax, ajax_gettable, csv_file, requires_account, render
from uber.errors import HTTPRedirect
from uber.forms import load_forms
from uber.models import Attendee, LotteryApplication
from uber.tasks.email import send_email
from uber.utils import RegistrationCode, validate_model, get_age_from_birthday, normalize_email_legacy


def _prepare_hotel_lottery_headers(attendee_id, attendee_email, token_type="X-SITE"):
    expiration_length = timedelta(minutes=30) if token_type == "MAGIC_LINK" else timedelta(seconds=30)
    return {
        'KEY': c.HOTEL_LOTTERY_KEY,
        'REG_ID': attendee_id,
        'EMAIL': base64.b64encode(attendee_email.encode()),
        'TOKEN': str(uuid.uuid4()),
        'TOKEN_TYPE': token_type,
        'TIMESTAMP': str(int(datetime.now().timestamp())),
        'EXPIRE': str(int((datetime.now() + expiration_length).timestamp()))
    }

@all_renderable(public=True)
class Root:
    @ajax
    @requires_account(Attendee)
    def check_duplicate_emails(self, session, id, **params):
        attendee = session.attendee(id)
        attendee_count = session.query(Attendee).filter(Attendee.hotel_lottery_eligible == True
                                                        ).filter(Attendee.normalized_email == attendee.normalized_email).count()
        return {'count': max(0, attendee_count - 1)}

    @requires_account(Attendee)
    def enter(self, session, id, room_owner=''):
        attendee = session.attendee(id)
        request_headers = _prepare_hotel_lottery_headers(attendee.id, attendee.email)
        response = requests.post(c.HOTEL_LOTTERY_API_URL, headers=request_headers, timeout=25)
        if response.json().get('success', False) == True:
            raise HTTPRedirect("{}?r={}&t={}{}".format(c.HOTEL_LOTTERY_FORM_LINK,
                                                       request_headers['REG_ID'],
                                                       request_headers['TOKEN'],
                                                       ('&p=' + room_owner) if room_owner else ''))
        else:
            log.error(f"We tried to register a token for the room lottery, but got an error: \
                      {response.json().get('message', response.text)}")
            raise HTTPRedirect("../preregistration/homepage?message={}", f"Sorry, something went wrong. Please try again in a few minutes.")

    @requires_account(Attendee)
    def send_link(self, session, id):
        attendee = session.attendee(id)
        request_headers = _prepare_hotel_lottery_headers(attendee.id, attendee.email, token_type="MAGIC_LINK")
        response = requests.post(c.HOTEL_LOTTERY_API_URL, headers=request_headers, timeout=25)
        if response.json().get('success', False) == True:
            lottery_link = "{}?r={}&t={}".format(c.HOTEL_LOTTERY_FORM_LINK,
                                                       request_headers['REG_ID'],
                                                       request_headers['TOKEN'])
            send_email.delay(
                    c.HOTELS_EMAIL,
                    attendee.email,
                    f'Entry link for the {c.EVENT_NAME_AND_YEAR} hotel lottery',
                    render('emails/hotel_lottery/magic_link.html', {'attendee': attendee, 'magic_link': lottery_link}, encoding=None),
                    'html',
                    model=attendee.to_dict('id'))
            raise HTTPRedirect("../preregistration/homepage?message={}", f"Email sent! Please ask {attendee.full_name} to check their email.")
        else:
            log.error(f"We tried to register a token for sending a link to the room lottery, but got an error: \
                      {response.json().get('message', response.text)}")
            raise HTTPRedirect("../preregistration/homepage?message={}", f"Sorry, the link could not be sent at this time. Please try again in a few minutes.")
        
    @requires_account(Attendee)
    def start(self, session, attendee_id, message="", **params):
        attendee = session.attendee(attendee_id)
        return {
            'attendee': attendee,
            'message': message,
        }

    @requires_account(Attendee)
    def terms(self, session, attendee_id, message="", **params):
        attendee = session.attendee(attendee_id)
        if attendee.lottery_application:
            application = attendee.lottery_application
        else:
            application = LotteryApplication(attendee_id=attendee_id)
        session.add(application)
        session.commit()
        
        forms_list = ["LotteryInfo"]
        forms = load_forms(params, application, forms_list)

        return {
            'id': application.id,
            'attendee_id': attendee_id,
            'forms': forms,
            'message': message,
            'application': application
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
        
        forms_list = ["LotteryInfo", "LotteryRoomGroup", "RoomLottery", "SuiteLottery"]
        forms = load_forms(params, application, forms_list)

        if cherrypy.request.method == 'POST':
            for form in forms.values():
                form.populate_obj(application)
            session.add(application)
            raise HTTPRedirect(f'index?attendee_id={attendee_id}')
        elif not application.terms_accepted:
            raise HTTPRedirect(f'terms?attendee_id={attendee_id}')

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
    def room_lottery(self, session, id=None, message="", **params):
        application = session.lottery_application(id)
        forms_list = ["RoomLottery"]

        if application.parent_application:
            if not application.parent_application.wants_room:
                message = "Your room group does not have an entry in the room lottery."
                raise HTTPRedirect(f'index?attendee_id={application.attendee.id}&messsage={message}')
            else:
                forms = load_forms(params, application.parent_application, forms_list)
                return {
                    'id': application.id,
                    'homepage_account': session.get_attendee_account_by_attendee(application.attendee),
                    'forms': forms,
                    'message': message,
                    'application': application,
                    'read_only': True,
                }
        
        forms = load_forms(params, application, forms_list)

        if cherrypy.request.method == 'POST':
            if not application.wants_room:
                entering_or_updating_str = "entering the room lottery"
                subject_str = "Confirmation"
            else:
                entering_or_updating_str = "updating your room lottery entry"
                subject_str = "Updated"
            for form in forms.values():
                form.populate_obj(application)

            session.commit()
            session.refresh(application)

            body = render('emails/hotel/room_lottery_entry.html', {
                'application': application,
                'entering_or_updating_str': entering_or_updating_str,}, encoding=None)
            send_email.delay(
                c.HOTEL_LOTTERY_EMAIL,
                application.attendee.email_to_address,
                c.EVENT_NAME_AND_YEAR + f' Room Lottery {subject_str}',
                body,
                model=application.to_dict('id'))
            raise HTTPRedirect('index?attendee_id={}&confirm=room&action={}',
                                application.attendee.id, subject_str.lower())

        return {
            'id': application.id,
            'homepage_account': session.get_attendee_account_by_attendee(application.attendee),
            'forms': forms,
            'message': message,
            'application': application,
            'read_only': False,
        }

    @requires_account(LotteryApplication)
    def withdraw_room(self, session, id=None, **params):
        application = session.lottery_application(id)

        if application.room_group_name:
            raise HTTPRedirect('room_lottery?id={}&message={}', application.id,
                               "Room groups must have a room lottery entry. You must disband the group first.")

        defaults = LotteryApplication().to_dict()
        for attr in ['earliest_room_checkin_date', 'latest_room_checkin_date',
                     'earliest_room_checkout_date', 'latest_room_checkout_date',
                     'hotel_preference', 'room_type_preference', 'room_selection_priorities',
                     'wants_ada', 'ada_requests', 'room_step', 'wants_room',
                     'legal_first_name', 'legal_last_name', 'terms_accepted', 'data_policy_accepted']:
            setattr(application, attr, defaults.get(attr))

        body = render('emails/hotel/lottery_entry_withdrawn.html', {
            'application': application, 'room_or_suite': 'standard room'}, encoding=None)
        send_email.delay(
            c.HOTEL_LOTTERY_EMAIL,
            application.attendee.email_to_address,
            c.EVENT_NAME_AND_YEAR + f' Room Lottery Entry Cancelled',
            body,
            model=application.to_dict('id'))

        raise HTTPRedirect('index?attendee_id={}&message={}',
                           application.attendee.id,
                           f"Room lottery entry canceled. You will receive an email confirming the cancellation.")
    
    @requires_account(LotteryApplication)
    def suite_lottery(self, session, id=None, message="", **params):
        application = session.lottery_application(id)
        forms_list = ["SuiteLottery"]

        if application.parent_application:
            if not application.parent_application.wants_suite:
                message = "Your room group does not have an entry in the suite lottery."
                raise HTTPRedirect(f'index?attendee_id={application.attendee.id}&messsage={message}')
            else:
                forms = load_forms(params, application.parent_application, forms_list)
                return {
                    'id': application.id,
                    'homepage_account': session.get_attendee_account_by_attendee(application.attendee),
                    'forms': forms,
                    'message': message,
                    'application': application,
                    'read_only': True,
                }

        forms = load_forms(params, application, forms_list)

        if cherrypy.request.method == 'POST':
            if not application.wants_suite:
                entering_or_updating_str = "entering the suite lottery"
                subject_str = "Confirmation"
            else:
                entering_or_updating_str = "updating your suite lottery entry"
                subject_str = "Updated"
            for form in forms.values():
                form.populate_obj(application)

            session.commit()
            session.refresh(application)

            body = render('emails/hotel/suite_lottery_entry.html', {
                'application': application,
                'entering_or_updating_str': entering_or_updating_str,}, encoding=None)
            send_email.delay(
                c.HOTEL_LOTTERY_EMAIL,
                application.attendee.email_to_address,
                c.EVENT_NAME_AND_YEAR + f' Suite Lottery {subject_str}',
                body,
                model=application.to_dict('id'))
            if subject_str == "Confirmation":
                for member in application.group_members:
                    body = render('emails/hotel/group_lottery_entry_added.html', {
                        'application': member, 'room_or_suite': 'suite'}, encoding=None)
                    send_email.delay(
                        c.HOTEL_LOTTERY_EMAIL,
                        member.attendee.email_to_address,
                        c.EVENT_NAME_AND_YEAR + f' Suite Lottery Entered',
                        body,
                        model=member.to_dict('id'))
            raise HTTPRedirect('index?attendee_id={}&confirm=suite&action={}',
                                application.attendee.id, subject_str.lower())

        return {
            'id': application.id,
            'homepage_account': session.get_attendee_account_by_attendee(application.attendee),
            'forms': forms,
            'message': message,
            'application': application,
            'read_only': False,
        }

    @requires_account(LotteryApplication)
    def withdraw_suite(self, session, id=None, **params):
        application = session.lottery_application(id)

        defaults = LotteryApplication().to_dict()
        for attr in ['earliest_suite_checkin_date', 'latest_suite_checkin_date',
                     'earliest_suite_checkout_date', 'latest_suite_checkout_date',
                     'hotel_preference', 'suite_type_preference', 'suite_selection_priorities',
                     'wants_ada', 'ada_requests', 'wants_suite', 'suite_step', 'suite_terms_accepted']:
            setattr(application, attr, defaults.get(attr))

        body = render('emails/hotel/lottery_entry_withdrawn.html', {
            'application': application, 'room_or_suite': 'suite'}, encoding=None)
        send_email.delay(
            c.HOTEL_LOTTERY_EMAIL,
            application.attendee.email_to_address,
            c.EVENT_NAME_AND_YEAR + f' Suite Lottery Entry Cancelled',
            body,
            model=application.to_dict('id'))
        for member in application.group_members:
            body = render('emails/hotel/group_suite_lottery_withdrawn.html', {
                'application': member, 'room_or_suite': 'suite'}, encoding=None)
            send_email.delay(
                c.HOTEL_LOTTERY_EMAIL,
                member.attendee.email_to_address,
                c.EVENT_NAME_AND_YEAR + f' Suite Lottery Entry Cancelled',
                body,
                model=member.to_dict('id'))
        extra_str = " and your room group's members" if application.group_members else ""
        raise HTTPRedirect('index?attendee_id={}&message={}',
                           application.attendee.id,
                           f"Suite lottery entry canceled. You{extra_str} will receive an email confirming the cancellation.")

    @requires_account(LotteryApplication)
    def withdraw_entries(self, session, id=None, **params):
        application = session.lottery_application(id)

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
        current_step = params.get('suite_step', params.get('room_step', 0))

        if current_step:
            # This is unusual for a validation function, but we want to save at each step of the form
            for form in forms.values():
                form.populate_obj(application)

            session.commit()

        return {"success": True, "step_completed": params.get('suite_step', params.get('room_step', 0))}
    
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
                raise HTTPRedirect('room_group?id={}&action={}', application.id, action)
    
    @requires_account(LotteryApplication)
    def new_invite_code(self, session, id=None, message="", **params):
        application = session.lottery_application(id)
        application.invite_code = RegistrationCode.generate_random_code(LotteryApplication.invite_code)
        raise HTTPRedirect('room_group?id={}&message={}', application.id,
                           f"New invite code generated. Your new code is {application.invite_code}.")
    
    @requires_account(LotteryApplication)
    def remove_group_member(self, session, id=None, member_id=None, message="", **params):
        application = session.lottery_application(id)
        member = session.lottery_application(member_id)
        member.parent_application = None
        session.commit()
        session.refresh(member)
        body = render('emails/hotel/removed_from_group.html', {
            'application': member, 'parent': application, 'group_disbanded': False}, encoding=None)
        send_email.delay(
            c.HOTEL_LOTTERY_EMAIL,
            member.attendee.email_to_address,
            f'Removed From {c.EVENT_NAME} Lottery Room Group "{application.room_group_name}"',
            body,
            model=member.to_dict('id'))
        raise HTTPRedirect('room_group?id={}&message={}', application.id,
                           f"{member.attendee.full_name} has been removed from your room group.")
    
    @requires_account(LotteryApplication)
    def delete_group(self, session, id=None, message="", **params):
        application = session.lottery_application(id)
        old_room_group_name = application.room_group_name
        application.room_group_name = ''
        application.invite_code = ''

        for member in application.group_members:
            member.parent_application = None
            session.add(member)
            session.commit()
            body = render('emails/hotel/removed_from_group.html', {
                'application': member, 'parent': application, 'group_disbanded': True}, encoding=None)
            send_email.delay(
                c.HOTEL_LOTTERY_EMAIL,
                member.attendee.email_to_address,
                f'{c.EVENT_NAME} Lottery Room Group "{application.room_group_name}" Disbanded',
                body,
                model=member.to_dict('id'))
        raise HTTPRedirect('index?attendee_id={}&message={}', application.attendee.id,
                           f"{old_room_group_name} has been disbanded.")

    @ajax
    def room_group_search(self, session, **params):
        invite_code, leader_email = params.get('invite_code'), params.get('leader_email')
        errors = []
        if not invite_code:
            errors.append("a group invite code")
        if not leader_email:
            errors.append("the room group leader's email address")
        if errors:
            return {'error': f"Please enter {readable_join(errors)}."}

        room_group = session.lookup_registration_code(invite_code, LotteryApplication)

        if not room_group or room_group.attendee.normalized_email != normalize_email_legacy(leader_email):
            return {'error': "No room group found. Please check the invite code and leader email address."}

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

        if cherrypy.request.method == "POST":
            if not params.get('room_group_id'):
                message = "Group ID invalid!"
            if not message:
                room_group = session.lottery_application(params.get('room_group_id'))
                if len(room_group.group_members) == 3:
                    message = "This room group is full."
                
                if message:
                    raise HTTPRedirect('room_group?id={}&message={}', application.id, message)

                application.parent_application = room_group

                body = render('emails/hotel/group_member_joined.html', {
                    'application': room_group, 'member': application}, encoding=None)
                send_email.delay(
                    c.HOTEL_LOTTERY_EMAIL,
                    room_group.attendee.email_to_address,
                    f'{application.attendee.first_name} has joined your {c.EVENT_NAME} Lottery Room Group',
                    body,
                    model=room_group.to_dict('id'))

                raise HTTPRedirect('room_group?id={}&action={}', application.id, "joined")
    
    @requires_account(LotteryApplication)
    def leave_group(self, session, id=None, message="", **params):
        application = session.lottery_application(id)

        if cherrypy.request.method == "POST":
            room_group = application.parent_application
            application.parent_application = None

            body = render('emails/hotel/group_member_left.html', {
                'application': room_group, 'member': application}, encoding=None)
            send_email.delay(
                c.HOTEL_LOTTERY_EMAIL,
                room_group.attendee.email_to_address,
                f'{application.attendee.first_name} has left your {c.EVENT_NAME} Lottery Room Group',
                body,
                model=room_group.to_dict('id'))

            raise HTTPRedirect('room_group?id={}&message={}', application.id,
                               f'Successfully left the room group "{room_group.room_group_name}".')
