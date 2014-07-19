from uber.common import *

@all_renderable(PEOPLE)
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

    def pending(self, session):
        approved = {ae.subject for ae in session.query(ApprovedEmail).all()}
        return {'pending': [rem for rem in Reminder.instances.values() if rem.needs_approval and rem.subject not in approved]}

    def pending_examples(self, session, subject):
        count = 0
        examples = []
        reminder = Reminder.instances[subject]
        attendees, groups = session.everyone()
        for x in (attendees if rem.model == Attendee else Group):
            if reminder.filter(x):
                count += 1
                url = ('../registration/form?id={}' if rem.model == Attendee else '../groups/form?id={}').format(x.id)
                if len(examples) < 10:
                    examples.append([url, reminder.render(x)])

        return {
            'count': count,
            'subject': subject,
            'examples': examples
        }

    @csrf_protected
    def approve(self, session, subject):
        session.add(ApprovedEmail(subject=subject))
        raise HTTPRedirect('pending?message={}', 'Email approved and will be sent out shortly')
