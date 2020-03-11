from datetime import datetime

from pockets import groupify, listify
from sqlalchemy import or_

from uber.automated_emails import AutomatedEmailFixture
from uber.config import c
from uber.decorators import ajax, all_renderable, csrf_protected, csv_file
from uber.errors import HTTPRedirect
from uber.models import AdminAccount, Attendee, AutomatedEmail, Email
from uber.tasks.email import send_email
from uber.utils import get_page


@all_renderable()
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

    def pending(self, session, message=''):
        emails_with_count = session.query(AutomatedEmail, AutomatedEmail.email_count).filter(
            AutomatedEmail.subject != '', AutomatedEmail.sender != '',).all()
        emails = []
        for email, email_count in sorted(emails_with_count, key=lambda e: e[0].ordinal):
            email.sent_email_count = email_count
            emails.append(email)

        emails_by_sender = groupify(emails, 'sender')

        return {
            'message': message,
            'automated_emails': emails_by_sender,
        }

    def pending_examples(self, session, ident, message=''):
        email = session.query(AutomatedEmail).filter_by(ident=ident).first()
        examples = []
        model = email.model_class
        query = AutomatedEmailFixture.queries.get(model)(session).order_by(model.id)
        limit = 1000
        for model_instance in query.limit(limit):
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
    
    def update_dates(self, session, ident, **params):
        email = session.query(AutomatedEmail).filter_by(ident=ident).first()
        email.apply(params, restricted=False)
        session.add(email)
        session.commit()
        raise HTTPRedirect('pending_examples?ident={}&message={}', ident, 'Email send dates updated')

    def test_email(self, session, subject=None, body=None, from_address=None, to_address=None, **params):
        """
        Testing only: send a test email as a system user
        """

        output_msg = ""

        if subject and body and from_address and to_address:
            send_email.delay(from_address, to_address, subject, body)
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
            try:
                # If this was an automated email, we can send out an updated copy
                if email.automated_email and email.fk:
                    email.automated_email.send_to(email.fk, delay=False, raise_errors=True)
                else:
                    send_email(
                        c.ADMIN_EMAIL,
                        email.fk_email,
                        email.subject,
                        email.body,
                        format=email.format,
                        model=email.fk.to_dict('id') if email.fk_id else None,
                        ident=email.ident)
                session.commit()
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
            raise HTTPRedirect(
                'pending?message={}',
                '"{}" approved and will be sent out {}'.format(automated_email.subject, 
                                                               "shortly" if not automated_email.active_when_label
                                                               else automated_email.active_when_label))
        raise HTTPRedirect('pending?message={}{}', 'Unknown automated email: ', ident)

    @csrf_protected
    def unapprove(self, session, ident):
        automated_email = session.query(AutomatedEmail).filter_by(ident=ident).first()
        if automated_email:
            automated_email.approved = False
            raise HTTPRedirect(
                'pending?message={}',
                'Approval to send "{}" rescinded, '
                'and it will not be sent until approved again'.format(automated_email.subject))
        raise HTTPRedirect('pending?message={}{}', 'Unknown automated email: ', ident)

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
