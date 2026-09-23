"""Changing the card on file via the secure-room wizard.

The capture iframe's postMessage is unreliable, so the wizard relies on
the PCI Vault webhook landing the new token on the assignment and the
card_status poll picking it up. The webhook used to treat ANY token
that differed from the stored one as a stale retry, so a changed card
was never saved and the page never advanced. Now a token from a capture
session opened after the stored card was captured replaces it.
"""

import io
import json
from datetime import datetime, timedelta, timezone

import cherrypy
import pytest

from uber.config import c
from uber.models import AutomatedEmail, Email

from tests.hotel.factories import (N, make_assignment, make_attendee,
                                   make_hotel, make_inventory)

SECRET = 'test-webhook-secret'


def _now():
    return datetime.now(timezone.utc)


def _iso(dt):
    return dt.isoformat()


def _room(session, **overrides):
    inv = make_inventory(session, make_hotel(session), quantity=2)
    return make_assignment(session, make_attendee(session), inv,
                           check_in=N[1], check_out=N[3], **overrides)


def _call_webhook(session, monkeypatch, body, secret=SECRET):
    from uber.site_sections.hotel_lottery import Root
    monkeypatch.setattr(c, 'VAULT_WEBHOOK_SECRET', SECRET, raising=False)
    monkeypatch.setattr(cherrypy.request, 'headers',
                        {'X-PCIVault-Webhook-Secret': secret}, raising=False)
    monkeypatch.setattr(cherrypy.request, 'body',
                        io.BytesIO(json.dumps(body).encode()), raising=False)
    monkeypatch.setattr(session, 'commit', session.flush)
    func = Root.vault_webhook
    while hasattr(func, '__wrapped__'):
        func = func.__wrapped__
    return func(Root(), session)


def test_webhook_saves_changed_card_and_its_metadata(session, monkeypatch):
    ra = _room(session, cc_token='tok-old', cc_last_four='1111',
               cc_captured_at=_now() - timedelta(minutes=10))

    result = _call_webhook(session, monkeypatch, {
        'metadata': {'assignment_id': ra.id,
                     'capture_started_at': _iso(_now())},
        'token_info': {
            'token': 'tok-new',
            'safe_data': json.dumps({'last_four': '2222', 'card_type': 'Mastercard'}),
            'card_metadata': {'issuer': [{'brand': 'Mastercard', 'issuing_bank': 'New Bank'}]},
        },
    })

    assert result == {'success': True}
    assert ra.cc_token == 'tok-new'
    assert ra.cc_last_four == '2222'
    assert ra.cc_card_type == 'Mastercard'
    assert ra.cc_issuer_bank == 'New Bank'


def test_webhook_ignores_stale_retry_for_replaced_card(session, monkeypatch):
    ra = _room(session, cc_token='tok-new', cc_last_four='2222',
               cc_captured_at=_now())

    result = _call_webhook(session, monkeypatch, {
        'metadata': {'assignment_id': ra.id,
                     'capture_started_at': _iso(_now() - timedelta(minutes=10))},
        'token_info': {'token': 'tok-old',
                       'safe_data': json.dumps({'last_four': '1111'})},
    })

    assert result == {'success': True}
    assert ra.cc_token == 'tok-new'
    assert ra.cc_last_four == '2222'


def test_webhook_bootstraps_missing_card(session, monkeypatch):
    ra = _room(session)

    _call_webhook(session, monkeypatch, {
        'metadata': {'assignment_id': ra.id, 'capture_started_at': _iso(_now())},
        'token_info': {'token': 'tok-new', 'safe_data': json.dumps({'last_four': '2222'})},
    })

    assert ra.cc_token == 'tok-new'
    assert ra.cc_last_four == '2222'
    assert ra.cc_captured_at is not None


def test_webhook_same_token_only_updates_metadata(session, monkeypatch):
    ra = _room(session, cc_token='tok-old', cc_captured_at=_now() - timedelta(minutes=10))

    _call_webhook(session, monkeypatch, {
        'metadata': {'assignment_id': ra.id},
        'token_info': {'token': 'tok-old', 'safe_data': json.dumps({'last_four': '1111'})},
    })

    assert ra.cc_token == 'tok-old'
    assert ra.cc_last_four == '1111'


@pytest.mark.parametrize('started', [None, '', 'not a date'])
def test_webhook_treats_undated_different_token_as_stale(session, monkeypatch, started):
    ra = _room(session, cc_token='tok-old', cc_captured_at=_now())
    metadata = {'assignment_id': ra.id}
    if started is not None:
        metadata['capture_started_at'] = started

    _call_webhook(session, monkeypatch, {
        'metadata': metadata,
        'token_info': {'token': 'tok-new', 'safe_data': json.dumps({'last_four': '2222'})},
    })

    assert ra.cc_token == 'tok-old'
    assert ra.cc_last_four is None


def test_webhook_replaces_when_stored_card_has_no_capture_time(session, monkeypatch):
    ra = _room(session, cc_token='tok-old', cc_captured_at=None)

    _call_webhook(session, monkeypatch, {
        'metadata': {'assignment_id': ra.id, 'capture_started_at': _iso(_now())},
        'token_info': {'token': 'tok-new'},
    })

    assert ra.cc_token == 'tok-new'


def test_webhook_rejects_bad_secret(session, monkeypatch):
    ra = _room(session)
    result = _call_webhook(session, monkeypatch, {
        'metadata': {'assignment_id': ra.id},
        'token_info': {'token': 'tok-new'},
    }, secret='wrong')
    assert 'error' in result
    assert ra.cc_token is None


@pytest.fixture
def secured_email_fixture(session):
    if not AutomatedEmail.initialized:
        AutomatedEmail.reconcile_fixtures()
        AutomatedEmail.initialized = True
    row = session.query(AutomatedEmail).filter_by(ident='hotel_lottery_secured').one()
    row.policy = c.AUTOSEND
    session.flush()
    return row


def _secure(session, ra, token):
    from uber.site_sections.hotel_lottery import Root
    func = Root.secure_room_callback
    while hasattr(func, '__wrapped__'):
        func = func.__wrapped__
    return func(Root(), session, token=token, assignment_id=ra.id,
                address1='1 Main St', city='Town', region='MD',
                zip_code='20001', country='United States')


def test_changing_card_on_secured_room_does_not_resend_confirmation(
        session, no_cherrypy_session, secured_email_fixture, monkeypatch):
    monkeypatch.setattr(session, 'commit', session.flush)
    ra = _room(session, status=c.ASSIGNED)

    assert _secure(session, ra, 'tok-first') == {'success': True}
    session.flush()
    assert ra.status == c.SECURED
    assert ra.cc_token == 'tok-first'
    emails = lambda: session.query(Email).filter_by(  # noqa: E731
        ident='hotel_lottery_secured', fk_id=ra.id).count()
    assert emails() == 1

    ra.cc_last_four = '1111'
    assert _secure(session, ra, 'tok-second') == {'success': True}
    session.flush()
    assert ra.cc_token == 'tok-second'
    assert ra.cc_last_four is None, 'a changed card drops the old metadata'
    assert ra.status == c.SECURED
    assert emails() == 1, 'a card change is not a new secure'
