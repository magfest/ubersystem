"""PCI Vault AOC link on the hotel lottery settings page.

PCI Vault publishes its current PCI DSS Attestation of Compliance only via
its authenticated API, proxied by uber-vault as `get_certificate`. Its
response shape is undocumented, so the client takes the first https:// URL
it finds and refuses anything else.
"""

import pytest

from uber import vault


@pytest.mark.parametrize('body,expected', [
    ({'url': 'https://example.invalid/aoc.pdf'}, 'https://example.invalid/aoc.pdf'),
    ({'certificate': {'link': 'https://example.invalid/a'}}, 'https://example.invalid/a'),
    ({'message': 'ok', 'links': ['https://example.invalid/b']}, 'https://example.invalid/b'),
    ('https://example.invalid/c', 'https://example.invalid/c'),
    ({'url': 'http://example.invalid/insecure'}, ''),
    ({'url': 'javascript:alert(1)'}, ''),
    ({'message': 'no certificate available'}, ''),
    ({}, ''),
    (None, ''),
])
def test_certificate_url_extraction(monkeypatch, body, expected):
    calls = []

    def fake_invoke(payload):
        calls.append(payload)
        return body

    monkeypatch.setattr(vault, '_invoke_lambda', fake_invoke)
    assert vault.get_certificate_url() == expected
    assert calls == [{'method': 'get_certificate'}]
