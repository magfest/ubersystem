"""Panel application emails: who qualifies, and what saving an application does to its unsent emails."""
import uuid
from datetime import datetime

import pytest
import pytz

from uber.automated_emails import PanelAppEmailFixture
from uber.config import c
from uber.email import EmailHandler, EmailService
from uber.models import (Attendee, AutomatedEmail, Department, Email, Event, PanelApplicant, PanelApplication,
                         Session)
from uber.tasks import panels
from uber.utils import slugify


@pytest.fixture
def departments(session):
    """Commit two departments with their own panel emails; setup_panel_emails reads them in its own session."""
    tag = uuid.uuid4().hex[:8]
    with Session() as s:
        depts = {name: Department(name=f'{name} {tag}', manages_panels=True, from_email=f'{name}{tag}@example.com')
                 for name in ('Arena', 'Makerspace')}
        s.add_all(depts.values())
        s.commit()
        dept_ids = {name: dept.id for name, dept in depts.items()}
    panels.setup_panel_emails(reconcile_fixtures=False)

    def ident(kind, name):
        return f'panelapps_{kind}_{slugify(f"{name} {tag}")}'

    with Session() as s:
        for email_ident in [i for i in AutomatedEmail._fixtures if tag in i]:
            row = AutomatedEmail(ident=email_ident).reconcile(AutomatedEmail._fixtures[email_ident])
            row.policy = c.AUTOSEND
            s.add(row)
        s.commit()
    yield dept_ids, ident
    # The test's open transaction holds locks on these departments.
    session.rollback()
    for email_ident in [i for i in AutomatedEmail._fixtures if tag in i]:
        AutomatedEmail._fixtures.pop(email_ident)
    with Session() as s:
        s.query(AutomatedEmail).filter(AutomatedEmail.ident.contains(tag)).delete(synchronize_session=False)
        s.query(Department).filter(Department.id.in_(dept_ids.values())).delete(synchronize_session=False)
        s.commit()


@pytest.fixture
def scratch(session):
    """Register a throwaway panel email with no filter; its row rolls back with the test."""
    made = []

    def build(**kwargs):
        ident = f'panelapps_scratch_{uuid.uuid4().hex[:8]}'
        made.append(ident)
        fixture = PanelAppEmailFixture('Subject', 'panels/panel_app_waitlisted.html', None, ident, **kwargs)
        row = AutomatedEmail(ident=ident).reconcile(fixture)
        session.add(row)
        session.flush()
        return row
    yield build
    for ident in made:
        AutomatedEmail._fixtures.pop(ident, None)


def _attendee(session, badge_type=c.ATTENDEE_BADGE):
    attendee = Attendee(first_name='Rosa', last_name='Ibarra', email=f'{uuid.uuid4().hex[:8]}@example.com',
                        badge_type=badge_type, badge_status=c.NEW_STATUS, paid=c.NEED_NOT_PAY, placeholder=True)
    session.add(attendee)
    session.flush()
    return attendee


def _application(session, department, status=c.ACCEPTED, attendee=None, event=None):
    applicant = PanelApplicant(first_name='Rosa', last_name='Ibarra', email=f'{uuid.uuid4().hex[:8]}@example.com',
                               attendee=attendee)
    session.add(applicant)
    session.flush()
    app = PanelApplication(name='Soldering 101', department=department, status=status, applicants=[applicant],
                           submitter_id=applicant.id, event=event, presentation=c.PRESENTATION_OPTS[0][0],
                           noise_level=c.NOISE_LEVEL_OPTS[0][0])
    session.add(app)
    session.flush()
    return app


def _link(session, app, badge_type=c.ATTENDEE_BADGE):
    app.submitter.attendee = _attendee(session, badge_type)
    session.flush()


def _row(session, ident):
    return session.query(AutomatedEmail).filter(AutomatedEmail.ident == ident).one()


def _queue(session, ident, app):
    row = _row(session, ident)
    EmailHandler(row, app, ident=ident).queue_email_obj(session)
    session.flush()
    return session.query(Email).filter(Email.ident == ident, Email.fk_id == app.id).one()


def _save(session, app):
    EmailService.check_emails_for_model(session, app)
    session.flush()


def _emails(session, app, kind='accepted'):
    return session.query(Email).filter(Email.fk_id == app.id, Email.ident.contains(f'_{kind}')).all()


@pytest.mark.parametrize('badge_type, qualifies', [(None, True), (c.ATTENDEE_BADGE, True), (c.STAFF_BADGE, True),
                                                   (c.GUEST_BADGE, False)])
def test_only_a_guest_badge_keeps_a_submitter_from_panel_emails(session, departments, badge_type, qualifies):
    dept_ids, ident = departments
    attendee = _attendee(session, badge_type) if badge_type else None
    own_dept = _application(session, dept_ids['Makerspace'], attendee=attendee)
    panels_dept = _application(session, str(c.PANELS), attendee=attendee)

    assert bool(AutomatedEmail._fixtures[ident('accepted', 'Makerspace')].filter(own_dept)) is qualifies
    assert bool(AutomatedEmail._fixtures['panel_accepted'].filter(panels_dept)) is qualifies


def test_an_application_with_no_submitter_still_qualifies(session, departments):
    dept_ids, ident = departments
    app = _application(session, dept_ids['Makerspace'])
    app.submitter_id = None

    assert AutomatedEmail._fixtures[ident('accepted', 'Makerspace')].filter(app)


def test_email_still_sends_when_a_badge_is_linked_while_it_waits(session, departments):
    dept_ids, ident = departments
    app = _application(session, dept_ids['Makerspace'])
    email = _queue(session, ident('accepted', 'Makerspace'), app)
    _link(session, app)

    EmailService.send_email(session, email, email.automated_email, app)
    session.flush()

    assert [e.status for e in _emails(session, app)] == [c.SENT]


@pytest.mark.parametrize('name', ['Arena', 'Makerspace'])
def test_saving_keeps_the_same_unsent_email(session, departments, name):
    # Both departments, so the result cannot depend on which one's email is checked first.
    dept_ids, ident = departments
    app = _application(session, dept_ids[name])
    _save(session, app)
    first = [e.id for e in _emails(session, app)]
    assert len(first) == 1

    for _ in range(3):
        _save(session, app)

    assert [e.id for e in _emails(session, app)] == first


def test_saving_deletes_the_unsent_email_once_the_application_stops_qualifying(session, departments):
    dept_ids, _ = departments
    app = _application(session, dept_ids['Makerspace'])
    _save(session, app)
    app.status = c.DECLINED

    _save(session, app)

    assert _emails(session, app) == []


def test_saving_still_deletes_an_unsent_email_that_belongs_to_no_automated_email(session, departments):
    dept_ids, _ = departments
    app = _application(session, dept_ids['Makerspace'], status=c.DECLINED)
    session.add(Email(ident='custom_accepted', shared_ident='panelapps_accepted', model='PanelApplication',
                      fk_id=app.id, to='x@example.com', subject='x', body='x', status=c.QUEUED))
    session.flush()

    _save(session, app)

    assert _emails(session, app) == []


def _sibling_email(session, app, row=None, ident='panelapps_accepted_sibling', shared_ident='panelapps_accepted'):
    email = Email(ident=ident, shared_ident=shared_ident, model='PanelApplication', fk_id=app.id, automated_email=row,
                  to='x@example.com', subject='x', body='x', status=c.UNAPPROVED)
    session.add(email)
    session.flush()
    return email


def test_saving_deletes_an_email_that_no_longer_applies_even_if_its_automated_email_is_off(session, departments):
    # Left behind, it would block the right department's email through the shared ident.
    dept_ids, ident = departments
    arena = _row(session, ident('accepted', 'Arena'))
    arena.policy = None
    app = _application(session, dept_ids['Makerspace'])
    _sibling_email(session, app, arena, ident=arena.ident)

    app.status = c.DECLINED
    _save(session, app)
    assert _emails(session, app) == []


def test_saving_deletes_an_email_whose_automated_email_is_not_in_the_code(session, departments):
    dept_ids, _ = departments
    orphan = AutomatedEmail(ident=f'panelapps_accepted_old-{uuid.uuid4().hex[:8]}', model='PanelApplication',
                            shared_ident='panelapps_accepted')
    session.add(orphan)
    session.flush()
    app = _application(session, dept_ids['Makerspace'])
    _sibling_email(session, app, orphan, ident=orphan.ident)

    _save(session, app)
    _save(session, app)

    assert [e.ident for e in _emails(session, app)] == [_row(session, departments[1]('accepted', 'Makerspace')).ident]


@pytest.mark.parametrize('status, kept', [(c.WAITLISTED, 1), (c.ACCEPTED, 0)])
def test_saving_keeps_an_action_email_only_while_its_send_filter_matches(session, departments, scratch, status, kept):
    # The automatic waitlist email has no filter, only a send filter, and shares an ident with ones that have filters.
    dept_ids, _ = departments
    row = scratch(send_filter='lambda app: app.status == c.WAITLISTED', shared_ident='panelapps_waitlisted')
    app = _application(session, dept_ids['Makerspace'], status=status)
    email = _sibling_email(session, app, row, ident=row.ident, shared_ident='panelapps_waitlisted')

    _save(session, app)

    assert session.query(Email).filter(Email.id == email.id).count() == kept


def test_filter_does_not_raise_before_a_new_badge_link_is_loaded(session, departments):
    dept_ids, ident = departments
    app = _application(session, dept_ids['Makerspace'])
    attendee = _attendee(session)
    assert app.submitter.attendee is None
    app.submitter.attendee_id = attendee.id

    assert AutomatedEmail._fixtures[ident('accepted', 'Makerspace')].filter(app)
    app.department = str(c.PANELS)
    assert AutomatedEmail._fixtures['panel_accepted'].filter(app)


def test_generating_includes_a_linked_submitter_and_waits_for_approval(session, departments, monkeypatch):
    dept_ids, ident = departments
    monkeypatch.setattr(session, 'commit', session.flush)
    app = _application(session, dept_ids['Makerspace'], attendee=_attendee(session))
    row = _row(session, ident('accepted', 'Makerspace'))
    row.policy = c.NEEDS_APPROVAL
    session.flush()

    assert EmailService.check_emails_for_fixture(session, row) == 1
    assert EmailService.check_emails_for_fixture(session, row) == 0
    assert [(e.status, e.send_after) for e in _emails(session, app)] == [(c.UNAPPROVED, None)]


def test_saving_under_needs_approval_waits_for_approval(session, departments):
    dept_ids, ident = departments
    _row(session, ident('accepted', 'Makerspace')).policy = c.NEEDS_APPROVAL
    session.flush()
    app = _application(session, dept_ids['Makerspace'], attendee=_attendee(session))

    _save(session, app)

    assert [(e.status, e.send_after) for e in _emails(session, app)] == [(c.UNAPPROVED, None)]


def test_email_is_deleted_when_a_guest_badge_is_linked_while_it_waits(session, departments):
    dept_ids, ident = departments
    app = _application(session, dept_ids['Makerspace'])
    email = _queue(session, ident('accepted', 'Makerspace'), app)
    _link(session, app, c.GUEST_BADGE)

    EmailService.send_email(session, email, email.automated_email, app)
    session.flush()

    assert _emails(session, app) == []


def test_scheduled_email_sent_under_the_old_shared_ident_is_not_repeated(session, monkeypatch):
    monkeypatch.setattr(session, 'commit', session.flush)
    event = Event(name='Soldering 101', start_time=datetime.now(pytz.UTC), duration=60)
    session.add(event)
    session.flush()
    app = _application(session, str(c.PANELS), event=event)
    row = _row(session, 'panel_scheduled')
    row.policy = c.NEEDS_APPROVAL
    email = _queue(session, 'panel_scheduled', app)
    email.status, email.shared_ident = c.SENT, 'panelapps_received'
    session.flush()

    assert EmailService.check_emails_for_fixture(session, row) == 0


def test_a_sent_email_is_never_queued_again(session, departments):
    dept_ids, ident = departments
    app = _application(session, dept_ids['Makerspace'])
    email = _queue(session, ident('accepted', 'Makerspace'), app)
    EmailService.send_email(session, email, email.automated_email, app)
    session.flush()
    _link(session, app)

    _save(session, app)
    _save(session, app)
    app.department = dept_ids['Arena']
    _save(session, app)
    _save(session, app)

    assert [(e.id, e.status) for e in _emails(session, app)] == [(email.id, c.SENT)]


def test_generating_skips_an_application_another_department_already_emailed(session, departments, monkeypatch):
    dept_ids, ident = departments
    monkeypatch.setattr(session, 'commit', session.flush)
    app = _application(session, dept_ids['Makerspace'])
    _queue(session, ident('accepted', 'Makerspace'), app).status = c.SENT
    app.department = dept_ids['Arena']
    session.flush()

    assert EmailService.check_emails_for_fixture(session, _row(session, ident('accepted', 'Arena'))) == 0


def test_scheduled_email_generates_for_an_application_that_got_the_received_email(session, monkeypatch):
    monkeypatch.setattr(session, 'commit', session.flush)
    event = Event(name='Soldering 101', start_time=datetime.now(pytz.UTC), duration=60)
    session.add(event)
    session.flush()
    app = _application(session, str(c.PANELS), event=event)
    _queue(session, 'panel_received', app).status = c.SENT
    row = _row(session, 'panel_scheduled')
    row.policy = c.NEEDS_APPROVAL
    session.flush()

    assert EmailService.check_emails_for_fixture(session, row) == 1
    assert EmailService.check_emails_for_fixture(session, row) == 0
