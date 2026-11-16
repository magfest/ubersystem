import inspect
import uuid

import pytest

from uber.config import c
from uber.email import EmailService
from uber.models import AttendeeAccount, PanelApplicant, PanelApplication, PasswordReset, Session
from uber.site_sections.panels_admin import Root

# The undecorated handler body; the ajax and access decorators need a live request.
create_badge = inspect.unwrap(Root.create_badge)


@pytest.fixture
def queued(monkeypatch):
    """Record queued emails as (ident, recipient email) pairs.

    The sso_account_setup fixture only registers when OIDC_ENABLED is set at import
    time, so the real queue cannot run here; production runs with OIDC on.
    """
    sent = []

    def fake_queue_email(session, ident='', to_model=None, **kwargs):
        sent.append((ident, to_model.email))
    monkeypatch.setattr(EmailService, 'queue_email', staticmethod(fake_queue_email))
    monkeypatch.setattr(c, 'ATTENDEE_ACCOUNTS_ENABLED', True)
    monkeypatch.setattr(type(c), 'LOCAL_ACCOUNTS_DISABLED', True)
    return sent


@pytest.fixture
def panel():
    """Commit an accepted panel submitted by one account, with one co-panelist who has no account."""
    tag = uuid.uuid4().hex[:8]
    emails = {'submitter': f'submitter-{tag}@mailinator.com', 'cohost': f'cohost-{tag}@mailinator.com'}
    with Session() as session:
        account = session.create_attendee_account(emails['submitter'])
        app = PanelApplication(name=f'Panel {tag}', status=c.ACCEPTED, attendee_account=account,
                               presentation=c.PRESENTATION_OPTS[0][0], noise_level=c.NOISE_LEVEL_OPTS[0][0])
        submitter = PanelApplicant(first_name='Dana', last_name='Okafor', email=emails['submitter'],
                                   submitter=True, applications=[app])
        cohost = PanelApplicant(first_name='Priya', last_name='Raman', email=emails['cohost'], applications=[app])
        session.add_all([app, submitter, cohost])
        session.flush()
        app.submitter_id = submitter.id
        session.commit()
        ids = {'app': app.id, 'submitter': submitter.id, 'cohost': cohost.id}

    yield ids, emails

    _delete_panel(ids, emails)


def _delete_panel(ids, emails):
    # ORM deletes, so SQLAlchemy also clears the panel_applicant_application and
    # attendee_attendee_account link rows. submitter_id has no relationship, so
    # it is cleared by hand before the applicant it points to is deleted.
    with Session() as session:
        app = session.get(PanelApplication, ids['app'])
        app.submitter_id = None
        session.flush()
        applicants = session.query(PanelApplicant).filter(
            PanelApplicant.id.in_([ids['submitter'], ids['cohost']])).all()
        attendees = [applicant.attendee for applicant in applicants if applicant.attendee]
        accounts = session.query(AttendeeAccount).filter(AttendeeAccount.email.in_(list(emails.values()))).all()
        for account in accounts:
            session.query(PasswordReset).filter(PasswordReset.attendee_id == account.id).delete()
            account.attendees.clear()
        for obj in applicants + [app] + accounts + attendees:
            session.delete(obj)
        session.commit()


def _create(applicant_id):
    with Session() as session:
        return create_badge(Root(), session, applicant_id=applicant_id)


def _managers(applicant_id):
    with Session() as session:
        return [account.email for account in session.get(PanelApplicant, applicant_id).attendee.managers]


def _accounts_for(email):
    with Session() as session:
        return session.query(AttendeeAccount).filter(AttendeeAccount.email == email).all()


def test_submitter_badge_goes_on_submitter_account(panel, queued):
    ids, emails = panel

    assert 'added' in _create(ids['submitter'])

    assert _managers(ids['submitter']) == [emails['submitter']]
    assert queued == [('attendee_account_attendee_added', emails['submitter'])]


def test_submitter_badge_follows_login_account_not_application_email(panel, queued):
    ids, emails = panel
    with Session() as session:
        session.get(PanelApplicant, ids['submitter']).email = 'dana.work@mailinator.com'
        session.commit()

    assert 'added' in _create(ids['submitter'])

    assert _managers(ids['submitter']) == [emails['submitter']]
    assert queued == [('attendee_account_attendee_added', emails['submitter'])]


def test_copanelist_without_account_gets_own_account_and_claim_email(panel, queued):
    ids, emails = panel

    assert 'added' in _create(ids['cohost'])

    assert _managers(ids['cohost']) == [emails['cohost']]
    assert queued == [('sso_account_setup', emails['cohost'])]
    [account] = _accounts_for(emails['cohost'])
    with Session() as session:
        assert session.query(PasswordReset).filter(PasswordReset.attendee_id == account.id).count() == 1


def test_copanelist_with_existing_account_is_added_to_it(panel, queued):
    ids, emails = panel
    with Session() as session:
        session.create_attendee_account(emails['cohost'])
        # Accounts match on normalized email, so a differently cased address still finds this one.
        session.get(PanelApplicant, ids['cohost']).email = emails['cohost'].upper()
        session.commit()

    assert 'added' in _create(ids['cohost'])

    assert _managers(ids['cohost']) == [emails['cohost']]
    assert queued == [('attendee_account_attendee_added', emails['cohost'])]
    assert len(_accounts_for(emails['cohost'])) == 1
