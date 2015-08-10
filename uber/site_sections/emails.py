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

    def pending(self, session, message=''):
        approved = {ae.subject for ae in session.query(ApprovedEmail).all()}
        return {
            'message': message,
            'pending': [ae for ae in AutomatedEmail.instances.values() if ae.needs_approval and ae.subject not in approved]
        }

    def pending_examples(self, session, subject):
        count = 0
        examples = []
        email = AutomatedEmail.instances[subject]
        attendees, groups = session.everyone()
        models = {Attendee: attendees, Group: groups}
        models.update({model: lister() for model, lister in AutomatedEmail.extra_models.items()})
        for x in models[email.model]:
            if email.filter(x):
                count += 1
                url = {
                    Group: '../groups/form?id={}',
                    Attendee: '../registration/form?id={}'
                }.get(x.__class__, '').format(x.id)
                if len(examples) < 10:
                    examples.append([url, email.render(x)])

        return {
            'count': count,
            'subject': subject,
            'examples': examples
        }

    @csrf_protected
    def approve(self, session, subject):
        session.add(ApprovedEmail(subject=subject))
        raise HTTPRedirect('pending?message={}', 'Email approved and will be sent out shortly')
