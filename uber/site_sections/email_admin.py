import cherrypy
from datetime import datetime, timedelta
import logging
import pytz
import traceback

from sqlalchemy import func, or_, any_

from uber.automated_emails import AutomatedEmailFixture
from uber.config import c
from uber.custom_tags import datetime_local_filter
from uber.decorators import ajax, all_renderable, csrf_protected, csv_file, any_admin_access, requires_email_admin, check_can_edit_dept
from uber.email import EmailHandler, EmailService
from uber.errors import HTTPRedirect
from uber.forms import load_forms
from uber.models import AdminAccount, Attendee, AutomatedEmail, Email, Department
from uber.utils import get_page, listify, groupify, validate_model
from uber.tasks.email import check_emails_for_fixture

log = logging.getLogger(__name__)


def filter_emails_by_dept_id(session, email_model, emails, department_id):
    depts_by_sender = {}

    if department_id == 'All':
        dept_ids = [str(d.id) for d in session.admin_attendee().dept_memberships_with_inherent_role]
    elif not department_id or department_id == 'None':
        dept_ids = [id for id, in session.query(Department.id)]
    elif department_id:
        dept_ids = [department_id]

    depts_by_sender = EmailService.emails_from_depts(session, dept_ids)
    dept_email_re = [fr'(^|<){email.replace('.', '\\.')}(>|$)' for email in depts_by_sender.keys()]

    if not department_id:
        return emails, depts_by_sender
    elif department_id == 'None':
        emails = emails.filter(~email_model.sender.regexp_match(any_(dept_email_re), flags="i"))
        if email_model == Email:
            emails = emails.filter(~Email.to.regexp_match(any_(dept_email_re), flags="i"))
    else:
        if email_model == Email:
            emails = emails.filter(or_(Email.sender.regexp_match(any_(dept_email_re), flags="i"),
                                       Email.to.regexp_match(any_(dept_email_re), flags="i")))
        else:
            emails = emails.filter(AutomatedEmail.sender.regexp_match(any_(dept_email_re), flags="i"))

    return emails, depts_by_sender


@all_renderable()
class Root:
    @requires_email_admin()
    def index(self, session, page='1', search_text='', status=[], subject=False, **params):
        emails = session.query(Email)
        search_text = search_text.strip()
        automated_email = None

        emails, depts_by_sender = filter_emails_by_dept_id(session, Email, emails, params.get('department_id', ''))

        if status:
            emails = emails.filter(Email.status.in_([int(s) for s in status]))
        
        ident = params.get('ident')
        if ident:
            emails = emails.filter(Email.ident == ident)
            automated_email = session.query(AutomatedEmail).filter(AutomatedEmail.ident == ident).first()

        if ident and 'send_after' not in params:
            send_after = True
        else:
            send_after = params.get('send_after', False)

        if not send_after:
            fifteen_mins = datetime.now(pytz.UTC) + timedelta(seconds=900)
            emails = emails.filter(or_(Email.send_after == None, Email.send_after < fifteen_mins))

        if search_text:
            if subject:
                emails = emails.icontains(Email.subject, search_text)
            else:
                emails = emails.icontains(Email.to, search_text)

        return {
            'page': page,
            'automated_email': automated_email,
            'emails': get_page(page, emails.order_by(Email.generated.desc())),
            'count': emails.count(),
            'search_text': search_text if not subject else '',
            'subject_search_text': search_text if subject else '',
            'department_id': params.get('department_id', ''),
            'depts_by_sender': depts_by_sender,
            'email_status': status or [str(val) for val in c.EMAIL_STATUS.keys()],
            'send_after': send_after,
        }

    @requires_email_admin()
    def sent(self, session, **params):
        return {'emails': session.query(Email).filter_by(**params).order_by(Email.generated).all()}

    @requires_email_admin()
    def pending(self, session, message='', policy='', **params):
        if not AutomatedEmail.initialized:
            AutomatedEmail.reconcile_fixtures()
            AutomatedEmail.initialized = True
            session.commit()

        emails = session.query(AutomatedEmail).filter(AutomatedEmail.subject != '', AutomatedEmail.sender != '')
        emails, depts_by_sender = filter_emails_by_dept_id(session, AutomatedEmail, emails, params.get('department_id', ''))

        if policy:
            emails = emails.filter(AutomatedEmail.policy == int(policy))

        for fixture in AutomatedEmail._fixtures.values():
            if not fixture.template_plugin_name or not fixture.template_path:
                fixture.update_template_plugin_info()

        queued_email_counts, sent_email_counts = {}, {}
        for email in emails:
            all_queued_emails = session.query(Email.id).filter(Email.automated_email_id == email.id)
            queued_email_counts[email.id] = all_queued_emails.filter(Email.status != c.SENT).count()
            sent_email_counts[email.id] = all_queued_emails.filter(Email.status == c.SENT).count()

        emails_by_sender = groupify(emails, 'sender')

        return {
            'message': message,
            'automated_emails': emails_by_sender,
            'queued_email_counts': queued_email_counts,
            'sent_email_counts': sent_email_counts,
            'depts_by_sender': depts_by_sender,
            'department_id': params.get('department_id', ''),
            'policy': policy,
        }
    
    @requires_email_admin()
    def automated_email(self, session, id, message='', **params):
        email = session.get(AutomatedEmail, id)
        depts_tuples = EmailService.depts_from_email(session, email.sender)
        if not c.HAS_FULL_EMAIL_ADMIN_ACCESS:
            if not depts_tuples:
                raise HTTPRedirect('pending?message={}',
                                   "You must have full email admin permissions to view or edit this email.")
            for department_id, _ in depts_tuples:
                message = check_can_edit_dept(session, department_id, 'dept_head')
                if not message:
                    break
            if message:
                raise HTTPRedirect('pending?message={}', message)

        forms = load_forms(params, email, ['EmailInfo'])
        
        limited_queue = False
        queued_emails = session.query(Email).filter(Email.automated_email_id == email.id)
        if queued_emails.limit(500).count() == 500:
            limited_queue = True
        unsent_count = queued_emails.filter(Email.status != c.SENT).limit(100).count()
        unapproved_count = queued_emails.filter(Email.status == c.UNAPPROVED).limit(100).count()
        error_count = queued_emails.filter(Email.status != c.SENT, Email.error != '').limit(100).count()

        fixture = email.fixture
        if not fixture.template_plugin_name or not fixture.template_path:
            fixture.update_template_plugin_info()

        if cherrypy.request.method == 'POST':
            for form in forms.values():
                form.populate_obj(email)
            session.add(email)
            session.commit()
            EmailService.reconcile_policy(session, email)
            message = "Email settings updated"
            if params.get('generate', False):
                if email.can_generate:
                    check_emails_for_fixture.delay(email.id)
                    message += " and email generation started"
                else:
                    message = +". This email is not eligible for generation due to the current settings"
            raise HTTPRedirect('automated_email?id={}&message={}', id, f'{message}.')
        
        return {
            'message': message,
            'email': email,
            'fixture': email.fixture,
            'email_depts': depts_tuples,
            'forms': forms,
            'limited_queue': limited_queue,
            'queued_emails': queued_emails.filter(Email.status.in_([c.QUEUED, c.UNAPPROVED])).all(),
            'error_count': error_count,
            'sent_emails': queued_emails.filter(Email.status == c.SENT).all(),
            'unsent_count': unsent_count,
            'unapproved_count': unapproved_count,
        }
    
    @ajax
    def validate_automated_email(self, session, form_list=[], **params):
        if params.get('id') in [None, '', 'None']:
            email = AutomatedEmail()
        else:
            email = session.automated_email(params.get('id'))

        if not form_list:
            form_list = ['EmailInfo']
        elif isinstance(form_list, str):
            form_list = [form_list]
        
        forms = load_forms(params, email, form_list)
        errors = validate_model(session, forms, email, is_admin=True)

        if errors:
            return {"error": errors}

        return {"success": True}
    
    @ajax
    @requires_email_admin()
    def generate_emails(self, session, id, **params):
        check_emails_for_fixture.delay(id)
        return {'success': True}
    
    @ajax
    def poll_email_generation(self, session, id, **params):
        email_check_status = c.REDIS_STORE.hgetall(c.REDIS_PREFIX + 'email_generation:' + id)
        if not email_check_status:
            return

        email_check_error = email_check_status.get('error', '')
        email_check_count = email_check_status.get('emails_generated', '')
        if email_check_error:
            c.REDIS_STORE.delete(c.REDIS_PREFIX + 'email_generation:' + id)
            return {"success": False, 'message': email_check_error}
        elif email_check_count:
            c.REDIS_STORE.delete(c.REDIS_PREFIX + 'email_generation:' + id)
            if email_check_count == '0':
                return {"success": True, 'message': "There were no new emails to generate."}
            return {"success": True, 'message': f"{email_check_count} emails generated."}
        
    @ajax
    @requires_email_admin('dept_head')
    def delete_email(self, session, id, **params):
        email = session.get(Email, id)
        if not email:
            return {"success": False, 'message': "This email has already been deleted."}
        if not email.error:
            return {"success": False, 'message': "This email does not have an error. Only emails with errors can be deleted."}
        session.delete(email)
        session.commit()
        return {"success": True, 'message': "Email deleted."}
    
    @ajax
    @requires_email_admin('dept_head')
    def requeue_email(self, session, id, **params):
        email = session.get(Email, id)
        if not email:
            return {"success": False, 'message': "Email not found."}

        email.error = ''
        email.status = c.QUEUED
        email_handler = EmailHandler(email_obj=email)
        if not email_handler.can_queue_email(session):
            return {"success": False, 'message': "This email cannot be queued and may be disabled."}

        email_handler.queue_email_obj(session)
        session.commit()
        return {"success": True, 'message': f"Email requeued and will be sent after {datetime_local_filter(email.send_after, '%x %X')}."}

    @requires_email_admin('dept_head')
    def reset_fixture_attr(self, session, ident, key):
        AutomatedEmail.reset_fixture_attr(session, ident, key)
        raise HTTPRedirect('index?ident={}&message={}',
                           ident, f'{key} has been reset to its original value')

    def test_email(self, session, subject=None, body=None, from_address=None, to_address=None, **params):
        """
        Testing only: send a test email as a system user
        """

        output_msg = ""

        if subject and body and from_address and to_address:
            EmailService.queue_email(session, to=to_address, sender=from_address,
                                     subject=subject, body=body)
            output_msg = "RAMS has attempted to send your email."

        right_now = str(datetime.now())

        return {
            'from_address': from_address or c.STAFF_EMAIL,
            'to_address': (
                to_address or
                ("goldenaxe75t6489@mailinator.com" if c.DEV_BOX else AdminAccount.admin_email())
                or ""),
            'subject':  c.EVENT_NAME_AND_YEAR + " test email " + right_now,
            'body': body or "ignore this email, <b>it is a test</b> of the <u>RAMS email system</u> " + right_now,
            'message': output_msg,
        }

    @any_admin_access
    @ajax
    def resend_email(self, session, id):
        """
        Resend a particular email to the model's current email address.

        This is useful for if someone had an invalid email address and did not receive an automated email.
        """
        email = session.email(id)
        if email:
            try:
                # If this was an automated email, we can send out an updated copy
                # TODO: Emails can now have both fixtures and custom subjects/senders/tos. How to resolve?
                if email.automated_email and email.fk:
                    email.automated_email.send_to(email.fk, delay=False, raise_errors=True)
                else:
                    send_email.delay(
                        c.ADMIN_EMAIL,
                        email.fk_email,
                        email.subject,
                        email.body,
                        format=email.format,
                        model=email.fk.to_dict('id') if email.fk_id else None,
                        ident=email.ident)
                session.commit()
            except Exception:
                traceback.print_exc()
                return {'success': False, 'message': 'Email not sent: unknown error.'}
            else:
                return {'success': True, 'message': 'Email resent.'}
        return {'success': False, 'message': 'Email not sent: no email found with that ID.'}

    @requires_email_admin()
    def emails_by_interest(self, message=''):
        return {
            'message': message
        }

    @requires_email_admin()
    @csv_file
    def emails_by_interest_csv(self, out, session, **params):
        """
        Generate a list of emails of attendees who match one of c.INTEREST_OPTS
        (interests are like "LAN", "music", "gameroom", etc)

        This is intended for use to export emails to a third-party email system, like MadMimi or Mailchimp
        """
        if 'interests' not in params:
            raise HTTPRedirect('emails_by_interest?message={}', 'You must select at least one interest')

        interests = [int(i) for i in listify(params['interests'])]
        assert all(k in c.INTERESTS for k in interests)

        attendees = session.query(Attendee).filter_by(can_spam=True).order_by('email').all()

        out.writerow(["fullname", "email", "zipcode"])

        for a in attendees:
            if set(interests).intersection(a.interests_ints):
                out.writerow([a.full_name, a.email, a.zip_code])

    @requires_email_admin()
    def emails_by_kickin(self, message=''):
        return {
            'message': message
        }

    @requires_email_admin()
    @csv_file
    def emails_by_kickin_csv(self, out, session, **params):
        """
        Generate a list of attendee emails by what kick-in level they've donated at.
        We also select attendees with kick-in levels above the selected level.
        """
        if 'amount_extra' not in params:
            raise HTTPRedirect('emails_by_kickin?message={}', 'You must select a kick-in level')

        amount_extra = params['amount_extra']

        base_filter = Attendee.badge_status.in_([c.NEW_STATUS, c.COMPLETED_STATUS])
        email_filter = [Attendee.can_spam == True] if 'only_can_spam' in params else []  # noqa: E712
        attendee_filter = Attendee.amount_extra >= amount_extra
        if 'include_staff' in params:
            attendee_filter = or_(attendee_filter, Attendee.badge_type == c.STAFF_BADGE)

        attendees = session.query(Attendee).filter(
            base_filter, attendee_filter, *email_filter).all()

        out.writerow(["fullname", "email", "zipcode"])
        for a in attendees:
            out.writerow([a.full_name, a.email, a.zip_code])
