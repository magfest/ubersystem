from uber.common import *


@all_renderable(c.PEOPLE)
class Root:
    def index(self, session, page='1'):
        emails = session.query(Email).order_by(Email.when.desc())
        return {
            'page': page,
            'emails': get_page(page, emails),
            'count': emails.count()
        }

    def sent(self, session, **params):
        return {'emails': session.query(Email).filter_by(**params).order_by(Email.when).all()}
    sent.restricted = [c.PEOPLE, c.REG_AT_CON]

    def pending(self, session, message=''):
        approved = {ae.ident for ae in session.query(ApprovedEmail).all()}
        approved_idents = AutomatedEmail.get_approved_idents(session).all()

        automated_emails = []
        for automated_email in AutomatedEmail.instances.values():
            automated_emails.append({
                'doesnt_need_approval': not automated_email.needs_approval,
                'approved': not automated_email.needs_approval or automated_email.ident in approved_idents,
                'automated_email': automated_email,
                'num_sent': session.query(Email).filter_by(ident=automated_email.ident).count(),
                'last_run_results':
                    SendAllAutomatedEmailsJob.last_result[automated_email.ident]
                    if SendAllAutomatedEmailsJob.last_result else None
            })

        return {
            'message': message,
            'pending': [ae for ae in AutomatedEmail.instances.values() if ae.needs_approval and ae.ident not in approved]
            'automated_emails': automated_emails,
            'last_run_result': SendAllAutomatedEmailsJob.last_result,
        }

    def pending_examples(self, session, ident):
        count = 0
        examples = []
        email = AutomatedEmail.instances[ident]
        for x in AutomatedEmail.queries[email.model](session):
            if email.filters_run(x):
                count += 1
                url = {
                    Group: '../groups/form?id={}',
                    Attendee: '../registration/form?id={}'
                }.get(x.__class__, '').format(x.id)
                if len(examples) < 10:
                    examples.append([url, email.render(x)])

        return {
            'count': count,
            'examples': examples,
            'subject': email.subject,
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
            'to_address': to_address or
                          ("goldenaxe75t6489@mailinator.com" if c.DEV_BOX else AdminAccount.admin_email())
                          or "",
            'subject':  c.EVENT_NAME_AND_YEAR + " test email " + right_now,
            'body': body or "ignore this email, <b>it is a test</b> of the <u>RAMS email system</u> " + right_now,
            'message': output_msg,
        }

    @csrf_protected
    def approve(self, session, ident):
        session.add(ApprovedEmail(ident=ident))
        raise HTTPRedirect('pending?message={}', 'Email approved and will be sent out shortly')

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
