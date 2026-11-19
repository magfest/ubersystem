import inspect
import threading
import time
import uuid
from datetime import date

import cherrypy
import pytest

from uber.config import c
from uber.email import EmailService
from uber.errors import HTTPRedirect
from uber.models import AttendeeAccount, BadgeWaitlistSignup, Session
from uber.site_sections import preregistration
from uber.site_sections.preregistration import Root

# The undecorated handler body; requires_account needs a live login.
waitlist_signup = inspect.unwrap(Root.waitlist_signup)

ADULT = c.ATTENDEE_BADGE


@pytest.fixture(autouse=True)
def waitlist_open(monkeypatch):
    monkeypatch.setattr(preregistration, 'check_waitlist_access', lambda **kwargs: '')
    monkeypatch.setattr(c, 'ATTENDEE_ACCOUNTS_ENABLED', True)
    monkeypatch.setattr(c, 'BADGE_WAITLIST_LIMITS', {ADULT: 2, c.CHILD_BADGE: 4})


@pytest.fixture(autouse=True)
def end_reservation(monkeypatch):
    """Give each test its own Redis keys and return a function that ends the form reservation.

    The handler stores the time the signup form was opened in Redis, per account, and
    every signup from that visit gets that time.
    """
    prefix = f'test-waitlist-{uuid.uuid4().hex[:8]}:'
    monkeypatch.setattr(c, 'REDIS_PREFIX', prefix)

    def end():
        c.REDIS_STORE.delete(prefix + 'waitlist_signup_reserved')
    yield end
    for key in c.REDIS_STORE.scan_iter(prefix + '*'):
        c.REDIS_STORE.delete(key)


@pytest.fixture(autouse=True)
def queued_emails(monkeypatch):
    sent = []

    def fake_queue_email(session, ident='', to_model=None, **kwargs):
        sent.append(ident)
    monkeypatch.setattr(EmailService, 'queue_email', staticmethod(fake_queue_email))
    return sent


@pytest.fixture
def account_id():
    with Session() as session:
        session.query(BadgeWaitlistSignup).delete()
        account = session.create_attendee_account(f'waitlist-dupes-{uuid.uuid4().hex[:8]}@mailinator.com')
        session.commit()
        account_id = account.id
    yield account_id
    with Session() as session:
        session.query(BadgeWaitlistSignup).delete()
        session.query(AttendeeAccount).filter(AttendeeAccount.id == account_id).delete()
        session.commit()


def person(first, last, birthdate='04/12/1990'):
    return {'first': first, 'last': last, 'birthdate': birthdate}


def form_params(*people):
    """Build the POST body the signup page sends for adult signups."""
    params = {'attendee_badge_signup_select': str(len(people)), 'child_badge_signup_select': '0'}
    for num, someone in enumerate(people, start=1):
        email = f'{someone["first"].strip().lower()}@mailinator.com'
        prefix = f'attendee_badge_{num}-'
        params.update({
            prefix + 'first_name': someone['first'],
            prefix + 'last_name': someone['last'],
            prefix + 'same_legal_name': '1',
            prefix + 'email': email,
            prefix + 'confirm_email': email,
            prefix + 'birthdate': someone['birthdate'],
        })
    return params


def submit(account_id, params):
    """POST the signup form for this account. Return the page message, or the redirect URL on success."""
    cherrypy.request.method = 'POST'
    with Session() as session:
        account = session.get(AttendeeAccount, account_id)
        session.current_attendee_account = lambda: account
        try:
            result = waitlist_signup(Root(), session, **params)
        except HTTPRedirect as redirect:
            session.commit()
            return redirect.urls[0]
        session.commit()
        return result['message']


def signups_for(account_id):
    with Session() as session:
        return sorted((s.first_name, s.status_label) for s in session.query(BadgeWaitlistSignup).filter(
            BadgeWaitlistSignup.attendee_account_id == account_id))


def test_one_submit_saves_each_person(account_id, queued_emails):
    result = submit(account_id, form_params(person('Dana', 'Okafor'), person('Kofi', 'Okafor')))

    assert 'homepage' in result
    assert signups_for(account_id) == [('Dana', 'Pending'), ('Kofi', 'Pending')]
    assert queued_emails == ['badge_waitlist_account_confirm']


def test_resubmitting_the_same_form_saves_each_person_once(account_id, queued_emails):
    params = form_params(person('Dana', 'Okafor'))
    submit(account_id, params)

    result = submit(account_id, params)

    assert 'homepage' in result
    assert signups_for(account_id) == [('Dana', 'Pending')]
    assert queued_emails == ['badge_waitlist_account_confirm']


def test_resubmitting_a_form_that_used_every_slot_still_succeeds(account_id):
    # The first submit used both adult slots, so the repeat must not hit the limit message.
    params = form_params(person('Dana', 'Okafor'), person('Kofi', 'Okafor'))
    submit(account_id, params)

    result = submit(account_id, params)

    assert 'homepage' in result
    assert signups_for(account_id) == [('Dana', 'Pending'), ('Kofi', 'Pending')]


def test_simultaneous_submits_save_each_person_once(account_id, monkeypatch):
    # Slow validation down so both requests are inside the handler at the same time.
    real_validate = preregistration.validate_model

    def slow_validate(*args, **kwargs):
        time.sleep(0.5)
        return real_validate(*args, **kwargs)
    monkeypatch.setattr(preregistration, 'validate_model', slow_validate)

    params = form_params(person('Dana', 'Okafor'))
    results = []
    threads = [threading.Thread(target=lambda: results.append(submit(account_id, params))) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert all('homepage' in result for result in results)
    assert signups_for(account_id) == [('Dana', 'Pending')]


def test_adding_someone_already_signed_up_in_a_new_visit_shows_a_message(account_id, end_reservation):
    submit(account_id, form_params(person('Dana', 'Okafor')))
    end_reservation()

    result = submit(account_id, form_params(person('Dana', 'Okafor')))

    assert result == 'There is already a waitlist signup for Dana Okafor.'
    assert signups_for(account_id) == [('Dana', 'Pending')]


def test_the_same_person_twice_in_one_form_shows_a_message(account_id):
    result = submit(account_id, form_params(person('Dana', 'Okafor'), person('Dana', 'Okafor')))

    assert result == 'Dana Okafor is listed more than once.'
    assert signups_for(account_id) == []


def test_names_match_regardless_of_case_and_spaces(account_id, end_reservation):
    submit(account_id, form_params(person('Mary', 'Ellis')))
    end_reservation()

    result = submit(account_id, form_params(person(' mary', 'ELLIS ')))

    assert result == 'There is already a waitlist signup for Mary Ellis.'
    assert signups_for(account_id) == [('Mary', 'Pending')]


def test_the_same_person_twice_in_one_form_matches_regardless_of_case(account_id):
    result = submit(account_id, form_params(person('Mary', 'Ellis'), person('mary ', 'ellis')))

    assert result == 'Mary Ellis is listed more than once.'
    assert signups_for(account_id) == []


def test_someone_who_cancelled_can_sign_up_again(account_id, end_reservation):
    submit(account_id, form_params(person('Dana', 'Okafor')))
    _set_status(account_id, c.CANCELLED)
    end_reservation()

    result = submit(account_id, form_params(person('Dana', 'Okafor')))

    assert 'homepage' in result
    assert signups_for(account_id) == [('Dana', 'Cancelled'), ('Dana', 'Pending')]


def test_cancelling_and_signing_up_again_in_the_same_visit_is_not_a_repeat(account_id):
    submit(account_id, form_params(person('Dana', 'Okafor')))
    _set_status(account_id, c.CANCELLED)

    result = submit(account_id, form_params(person('Dana', 'Okafor')))

    assert 'homepage' in result
    assert signups_for(account_id) == [('Dana', 'Cancelled'), ('Dana', 'Pending')]


def test_someone_removed_by_an_admin_cannot_sign_up_again(account_id, end_reservation):
    submit(account_id, form_params(person('Dana', 'Okafor')))
    _set_status(account_id, c.REMOVED)
    end_reservation()

    result = submit(account_id, form_params(person('Dana', 'Okafor')))

    assert result == 'There is already a waitlist signup for Dana Okafor.'


def _set_status(account_id, status):
    with Session() as session:
        session.query(BadgeWaitlistSignup).filter(BadgeWaitlistSignup.attendee_account_id == account_id).update(
            {BadgeWaitlistSignup.status: status})
        session.commit()


def test_different_birthdates_are_different_people(account_id):
    result = submit(account_id, form_params(person('Priya', 'Raman', '05/05/2001'),
                                            person('Priya', 'Raman', '07/07/2003')))

    assert 'homepage' in result
    assert signups_for(account_id) == [('Priya', 'Pending'), ('Priya', 'Pending')]


def test_someone_signed_up_on_another_account_shows_a_message(account_id):
    with Session() as session:
        other = session.create_attendee_account(f'waitlist-other-{uuid.uuid4().hex[:8]}@mailinator.com')
        session.add(BadgeWaitlistSignup(attendee_account=other, waitlist_type=ADULT, first_name='Dana',
                                        last_name='Okafor', birthdate=date(1990, 4, 12)))
        session.commit()
        other_id = other.id

    result = submit(account_id, form_params(person('Dana', 'Okafor')))

    assert result == 'There is already a waitlist signup for Dana Okafor.'
    assert signups_for(account_id) == []
    with Session() as session:
        session.query(BadgeWaitlistSignup).filter(BadgeWaitlistSignup.attendee_account_id == other_id).delete()
        session.query(AttendeeAccount).filter(AttendeeAccount.id == other_id).delete()
        session.commit()
