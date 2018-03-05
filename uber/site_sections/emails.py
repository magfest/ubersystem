from datetime import datetime

from pockets import listify
from sqlalchemy import or_

from uber.automated_emails import AutomatedEmailFixture
from uber.config import c
from uber.decorators import ajax, all_renderable, csrf_protected, csv_file
from uber.errors import HTTPRedirect
from uber.models import AdminAccount, Attendee, AutomatedEmail, Email
from uber.notifications import send_email
from uber.utils import get_page


@all_renderable(c.PEOPLE)
class Root:
    def index(self, session, page='1', search_text=''):
        emails = session.query(Email).order_by(Email.when.desc())
        search_text = search_text.strip()
        if search_text:
            emails = emails.icontains(Email.to, search_text)
        return {
            'page': page,
            'emails': get_page(page, emails),
            'count': emails.count(),
            'search_text': search_text
        }

    def sent(self, session, **params):
        return {'emails': session.query(Email).filter_by(**params).order_by(Email.when).all()}
    sent.restricted = [c.PEOPLE, c.REG_AT_CON]

    def pending(self, session, message=''):
        automated_emails_with_count = session.query(AutomatedEmail, AutomatedEmail.email_count).all()
        automated_emails = []
        for automated_email, email_count in automated_emails_with_count:
            automated_email.sent_email_count = email_count
            automated_emails.append(automated_email)

        return {
            'message': message,
            'automated_emails': sorted(automated_emails, key=lambda e: e.ordinal),
        }

    def pending_examples(self, session, ident):
        email = session.query(AutomatedEmail).filter_by(ident=ident).first()
        examples = []
        for model_instance in AutomatedEmailFixture.queries[email.model_class](session):
            if email.would_send_if_approved(model_instance):
                examples.append((model_instance, email.render_body(model_instance).decode('utf-8')))
                if len(examples) > 4:
                    break
        return {
            'email': email,
            'examples': examples,
        }

    def test_email(self, session, subject=None, body=None, from_address=None, to_address=None, **params):
        """
        Testing only: send a test email as a system user
        """

        output_msg = ""

        if subject and body and from_address and to_address:
            send_email(from_address, to_address, subject, body)
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

    @ajax
    def resend_email(self, session, id):
        """
        Resend a particular email to the model's current email address.

        This is useful for if someone had an invalid email address and did not receive an automated email.
        """

        email = session.email(id)
        if email:
            # If this was an automated email, we can send out an updated template with the correct 'from' address
            if email.ident in AutomatedEmailFixture.fixtures_by_ident:
                email_category = AutomatedEmailFixture.fixtures_by_ident[email.ident]
                sender = email_category.sender
                body = email_category.render(email.fk)
            else:
                sender = c.ADMIN_EMAIL
                body = email.html

            try:
                send_email(sender, email.rcpt_email, email.subject, body, model=email.fk, ident=email.ident)
            except Exception:
                return {'success': False, 'message': 'Email not sent: unknown error.'}
            else:
                return {'success': True, 'message': 'Email resent.'}
        return {'success': False, 'message': 'Email not sent: no email found with that ID.'}

    @csrf_protected
    def approve(self, session, ident):
        automated_email = session.query(AutomatedEmail).filter_by(ident=ident).first()
        if automated_email:
            automated_email.approved = True
            raise HTTPRedirect('pending?message={}', 'Email approved and will be sent out shortly')
        raise HTTPRedirect('pending?message={}{}', 'Unknown email template: ', ident)

    def emails_by_interest(self, message=''):
        return {
            'message': message
        }

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

    def emails_by_kickin(self, message=''):
        return {
            'message': message
        }

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
