import time

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import jwk, jwt

from uber.auth import OIDC
from uber.config import c


@pytest.fixture(scope='module')
def private_pem():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()).decode()


@pytest.fixture
def oidc(monkeypatch, private_pem):
    instance = OIDC()
    public_jwk = jwk.construct(private_pem, 'RS256').public_key().to_dict()
    public_jwk['kid'] = 'test'
    monkeypatch.setattr(instance, '_fetch_key', lambda kid: public_jwk)
    return instance


@pytest.fixture
def sign(private_pem):
    def _sign(**claims):
        claims.setdefault('sub', 'abc')
        claims.setdefault('exp', int(time.time()) + 300)
        return jwt.encode(claims, private_pem, algorithm='RS256', headers={'kid': 'test'})
    return _sign


def test_api_audience_accepted(oidc, sign):
    assert oidc._verify_token(sign(aud='ubersystem-api'), audience='ubersystem-api')['sub'] == 'abc'


def test_login_id_token_rejected_by_api_audience(oidc, sign, monkeypatch, capsys):
    monkeypatch.setattr(c, 'OIDC_CLIENT_ID', 'rams-local-dev')
    assert not oidc._verify_token(sign(aud='rams-local-dev'), audience='ubersystem-api')


def test_api_token_rejected_by_login_verification(oidc, sign, monkeypatch, capsys):
    monkeypatch.setattr(c, 'OIDC_CLIENT_ID', 'rams-local-dev')
    assert not oidc._verify_token(sign(aud='ubersystem-api'))


def test_default_audience_is_login_client(oidc, sign, monkeypatch):
    monkeypatch.setattr(c, 'OIDC_CLIENT_ID', 'rams-local-dev')
    assert oidc._verify_token(sign(aud='rams-local-dev'))['sub'] == 'abc'


def test_empty_audience_does_not_fall_back_to_login_client(oidc, sign, monkeypatch, capsys):
    monkeypatch.setattr(c, 'OIDC_CLIENT_ID', 'rams-local-dev')
    assert not oidc._verify_token(sign(aud='rams-local-dev'), audience='')


def test_api_audience_rejects_token_without_aud(oidc, sign, capsys):
    assert not oidc._verify_token(sign(), audience='ubersystem-api')


def test_login_verification_accepts_token_without_aud(oidc, sign, monkeypatch):
    monkeypatch.setattr(c, 'OIDC_CLIENT_ID', 'rams-local-dev')
    assert oidc._verify_token(sign())['sub'] == 'abc'


def test_api_audience_rejects_token_without_exp(oidc, private_pem, capsys):
    token = jwt.encode({'sub': 'abc', 'aud': 'ubersystem-api'}, private_pem, algorithm='RS256', headers={'kid': 'test'})
    assert not oidc._verify_token(token, audience='ubersystem-api')
