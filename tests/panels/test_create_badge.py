import inspect
import uuid

import pytest
from sqlalchemy import func

from uber.config import c
from uber.email import EmailService
from uber.models import Attendee, AttendeeAccount, PanelApplicant, PanelApplication, PasswordReset, Session
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
        submitter = PanelApplicant(first_name='Dana', last_name=f'Okafor{tag}', email=emails['submitter'],
                                   submitter=True, applications=[app])
        cohost = PanelApplicant(first_name='Priya', last_name=f'Raman{tag}', email=emails['cohost'], applications=[app])
        session.add_all([app, submitter, cohost])
        session.flush()
        app.submitter_id = submitter.id
        session.commit()
        ids = {'app': app.id, 'submitter': submitter.id, 'cohost': cohost.id, 'tag': tag}

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
        applicants = list(app.applicants)
        # A failing run can leave badges no applicant points to, so badges are also found by email.
        attendees = {applicant.attendee for applicant in applicants if applicant.attendee}
        attendees |= set(session.query(Attendee).filter(func.lower(Attendee.email).in_(list(emails.values()))))
        accounts = set(session.query(AttendeeAccount).filter(AttendeeAccount.email.in_(list(emails.values()))))
        accounts |= {account for attendee in attendees for account in attendee.managers}
        for account in accounts:
            session.query(PasswordReset).filter(PasswordReset.attendee_id == account.id).delete()
            account.attendees.clear()
        for obj in applicants + [app] + list(accounts) + list(attendees):
            session.delete(obj)
        session.commit()


def _create(applicant_id, **params):
    with Session() as session:
        return create_badge(Root(), session, applicant_id=applicant_id, **params)


def _managers(applicant_id):
    with Session() as session:
        return [account.email for account in session.get(PanelApplicant, applicant_id).attendee.managers]


def _accounts_for(email):
    with Session() as session:
        return session.query(AttendeeAccount).filter(AttendeeAccount.email == email).all()


def _badge_count(email):
    with Session() as session:
        return session.query(Attendee).filter(func.lower(Attendee.email) == email.lower()).count()


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


def test_copanelist_without_email_gets_a_badge_but_no_account(panel, queued):
    ids, _ = panel
    with Session() as session:
        session.get(PanelApplicant, ids['cohost']).email = ''
        session.commit()
    blank_accounts = len(_accounts_for(''))

    assert 'added' in _create(ids['cohost'])

    assert _managers(ids['cohost']) == []
    assert queued == []
    assert len(_accounts_for('')) == blank_accounts


def _add_earlier_row(ids, emails, badge_status=c.NEW_STATUS):
    """Give the co-panelist a second applicant row, as for a second panel, already linked to a badge."""
    last_name = f'Raman{ids["tag"]}'
    with Session() as session:
        badge = Attendee(first_name='Priya', last_name=last_name, email=emails['cohost'], paid=c.NEED_NOT_PAY,
                         placeholder=True, badge_status=badge_status)
        session.add(badge)
        session.flush()
        earlier = PanelApplicant(first_name='Priya', last_name=last_name, email=emails['cohost'], attendee_id=badge.id,
                                 applications=[session.get(PanelApplication, ids['app'])])
        session.add(earlier)
        session.commit()
        return badge.id, earlier.id


def _linked_badge(applicant_id):
    with Session() as session:
        return session.get(PanelApplicant, applicant_id).attendee_id


def test_second_press_does_not_make_another_badge(panel, queued):
    ids, emails = panel
    assert 'added' in _create(ids['cohost'])

    result = _create(ids['cohost'])

    assert 'Reload the page' in result['error']
    assert _badge_count(emails['cohost']) == 1
    assert queued == [('sso_account_setup', emails['cohost'])]


def test_badge_on_another_applicant_row_is_not_replaced(panel, queued):
    ids, emails = panel
    badge_id, earlier_id = _add_earlier_row(ids, emails)

    result = _create(ids['cohost'])

    # The row stays listed after a reload, so the admin needs Link, not Reload.
    assert 'Link' in result['error']
    assert _linked_badge(earlier_id) == badge_id
    assert _badge_count(emails['cohost']) == 1
    assert queued == []


def test_invalid_badge_on_another_applicant_row_does_not_block(panel, queued):
    ids, emails = panel
    invalid_id, earlier_id = _add_earlier_row(ids, emails, badge_status=c.INVALID_STATUS)

    assert 'added' in _create(ids['cohost'])

    new_id = _linked_badge(ids['cohost'])
    assert new_id != invalid_id
    assert _linked_badge(earlier_id) == new_id
    assert queued == [('sso_account_setup', emails['cohost'])]


def _family_badge_count(family):
    with Session() as session:
        return session.query(Attendee).filter(Attendee.last_name == family.last).count()


def test_possible_match_asks_and_creates_nothing(family, queued):
    before = _family_badge_count(family)

    result = _create(family.ids['jim_row'])

    assert 'Jimmy' in result['confirm'] and 'matches email and name' in result['confirm']
    assert _family_badge_count(family) == before
    assert queued == []


def test_confirmed_create_adds_badge(family, queued):
    assert 'added' in _create(family.ids['jim_row'], confirmed='1')

    assert _linked_badge(family.ids['jim_row']) not in family.ids.values()


def _invalidate(*badge_ids):
    with Session() as session:
        for badge_id in badge_ids:
            session.get(Attendee, badge_id).badge_status = c.INVALID_STATUS
        session.commit()


def test_sibling_badge_linked_to_sibling_does_not_ask(family, queued):
    _invalidate(family.ids['jimmy'], family.ids['jim_work'])
    family.add_row('Sarah', 'app', 'sarah')

    assert 'added' in _create(family.ids['jim_row'])


def test_own_name_badge_linked_to_someone_else_still_asks(family, queued):
    # A badge matching this panelist's name, mislinked to a sibling, is still likely this panelist's.
    _invalidate(family.ids['jim_work'])
    family.add_row('Sarah', 'app', 'sarah')
    family.add_row('Sarah', 'other_app', 'jimmy')

    assert 'Jimmy' in _create(family.ids['jim_row'])['confirm']
