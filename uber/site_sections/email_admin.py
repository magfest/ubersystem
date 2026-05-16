from datetime import datetime
import traceback

from sqlalchemy import func, or_

from uber.automated_emails import AutomatedEmailFixture
from uber.config import c
from uber.decorators import ajax, all_renderable, csrf_protected, csv_file, any_admin_access, requires_email_admin
from uber.email import EmailService
from uber.errors import HTTPRedirect
from uber.models import AdminAccount, Attendee, AutomatedEmail, Email, Department
from uber.utils import get_page, listify, groupify


def filter_emails_by_dept_id(session, emails, department_id):
    depts_by_sender = {}
    if department_id == 'All':
        dept_ids = [str(d.id) for d in session.admin_attendee().dept_memberships_with_inherent_role]
        depts_by_sender = EmailService.get_emails_from_depts(session, dept_ids)
        dept_emails = depts_by_sender.keys()
        emails = emails.filter(or_(Email.sender.in_(dept_emails), Email.to.in_(dept_emails)))
    elif department_id == 'None':
        depts_by_sender = EmailService.get_emails_from_depts(session, [id for id, in session.query(Department.id)])
        dept_emails = depts_by_sender.keys()
        emails = emails.filter(~Email.sender.in_(dept_emails), ~Email.to.in_(dept_emails))
    elif department_id:
        depts_by_sender = EmailService.get_emails_from_depts(session, [department_id])
        dept_emails = depts_by_sender.keys()
        emails = emails.filter(or_(Email.sender.in_(dept_emails), Email.to.in_(dept_emails)))

    return emails, depts_by_sender


@all_renderable()
class Root:
    @requires_email_admin
    def index(self, session, page='1', search_text='', status=None, subject=False, **params):
        emails = session.query(Email)
        search_text = search_text.strip()

        emails, depts_by_sender = filter_emails_by_dept_id(session, emails, params.get('department_id', ''))

        if status:
            emails = emails.filter(Email.status == int(status))

        if search_text:
            if subject:
                emails = emails.icontains(Email.subject, search_text)
            else:
                emails = emails.icontains(Email.to, search_text)

        if params.get('ident'):
            emails = emails.filter(Email.ident == params.get('ident'))

        return {
            'page': page,
            'emails': get_page(page, emails.order_by(Email.generated)),
            'count': emails.count(),
            'search_text': search_text if not subject else '',
            'subject_search_text': search_text if subject else '',
            'department_id': params.get('department_id', ''),
            'depts_by_sender': depts_by_sender,
            'status': status,
        }

    @requires_email_admin
    def sent(self, session, **params):
        return {'emails': session.query(Email).filter_by(**params).order_by(Email.generated).all()}

    @requires_email_admin
    def pending(self, session, message='', policy=None, **params):
        emails = session.query(AutomatedEmail).filter(AutomatedEmail.subject != '', AutomatedEmail.sender != '')
        emails, depts_by_sender = filter_emails_by_dept_id(session, emails, params.get('department_id', ''))

        if policy:
            emails = emails.filter(AutomatedEmail.policy == int(policy))

        for fixture in AutomatedEmail._fixtures.values():
            if not fixture.template_plugin_name or not fixture.template_url:
                fixture.update_template_plugin_info()

        queued_email_counts, sent_email_counts = {}, {}
        for email in emails:
            queued_email_counts[email.id] = session.query(Email).filter(Email.automated_email_id == email.id,
                                                                        Email.status != c.SENT).count()
            sent_email_counts[email.id] = session.query(Email).filter(Email.automated_email_id == email.id,
                                                                      Email.status == c.SENT).count()

        emails_by_sender = groupify(emails, 'sender')

        return {
            'message': message,
            'automated_emails': emails_by_sender,
            'queued_email_counts': queued_email_counts,
            'sent_email_counts': sent_email_counts,
            'depts_by_sender': depts_by_sender,
        }

    @requires_email_admin
    def pending_examples(self, session, ident, message=''):
        email = session.query(AutomatedEmail).filter_by(ident=ident).first()
        examples = []
        model = email.model_class
        query = AutomatedEmailFixture.queries.get(model)(session).order_by(model.id)
        limit = 1000
        for model_instance in query.order_by(func.random()).limit(limit):
            if email.would_send_if_approved(model_instance):
                # These examples are never added to the session or saved to the database.
                # They are only used to render an example of the automated email.
                example = Email(
                    subject=email.render_subject(model_instance),
                    body=email.render_body(model_instance),
                    sender=email.sender,
                    to=model_instance.email,
                    cc=email.cc,
                    bcc=email.bcc,
                    replyto=email.replyto,
                    ident=email.ident,
                    fk_id=model_instance.id,
                    automated_email_id=email.id,
                    automated_email=email,
                )
                examples.append((model_instance, example))
                example_count = len(examples)
                if example_count > 10:
                    break
        return {
            'email': email,
            'examples': examples,
            'message': message,
        }

    @requires_email_admin
    def update_dates(self, session, ident, **params):
        #AutomatedEmail.update_fixture(session, ident, **params)
        raise HTTPRedirect('pending_examples?ident={}&message={}', ident, 'Email send dates updated')

    @requires_email_admin('dept_head')
    def reset_fixture_attr(self, session, ident, key):
        AutomatedEmail.reset_fixture_attr(session, ident, key)
        raise HTTPRedirect('pending_examples?ident={}&message={}',
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

    @requires_email_admin('dept_head')
    @csrf_protected
    def approve(self, session, ident):
        automated_email = session.query(AutomatedEmail).filter_by(ident=ident).first()
        if automated_email:
            automated_email.policy = c.AUTOSEND
            raise HTTPRedirect(
                'pending?message={}',
                '"{}" approved and will be sent out {}'.format(automated_email.subject,
                                                               "shortly" if not automated_email.active_when_label
                                                               else automated_email.active_when_label))
        raise HTTPRedirect('pending?message={}{}', 'Unknown automated email: ', ident)

    @requires_email_admin
    @csrf_protected
    def unapprove(self, session, ident):
        automated_email = session.query(AutomatedEmail).filter_by(ident=ident).first()
        if automated_email:
            automated_email.policy = c.NEEDS_APPROVAL
            raise HTTPRedirect(
                'pending?message={}',
                'Approval to send "{}" rescinded, '
                'and it will not be sent until approved again'.format(automated_email.subject))
        raise HTTPRedirect('pending?message={}{}', 'Unknown automated email: ', ident)

    @requires_email_admin
    def emails_by_interest(self, message=''):
        return {
            'message': message
        }

    @requires_email_admin
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

    @requires_email_admin
    def emails_by_kickin(self, message=''):
        return {
            'message': message
        }

    @requires_email_admin
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
