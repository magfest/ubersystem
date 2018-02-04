import pytest

from uber.barcode.utils import generate_barcode_from_badge_num, \
    get_badge_num_from_barcode, assert_is_valid_rams_barcode
from uber.config import c


@pytest.fixture
def cfg(monkeypatch):
    monkeypatch.setattr(c, 'BARCODE_KEY', 'ABCDEF1234')
    monkeypatch.setattr(c, 'BARCODE_SALT', 42)
    monkeypatch.setattr(c, 'BARCODE_EVENT_ID', 0xFF)


def test_cfg_fixtures(cfg):
    assert c.BARCODE_KEY == 'ABCDEF1234'
    assert c.BARCODE_SALT == 42
    assert c.BARCODE_EVENT_ID == 0xFF


def test_encrypt_decrypt(cfg):
    badge_num = 3
    encrypted = generate_barcode_from_badge_num(badge_num=badge_num)

    assert len(encrypted) == 7
    decrypted = get_badge_num_from_barcode(barcode_num=encrypted)

    assert decrypted['badge_num'] == badge_num
    assert decrypted['event_id'] == c.BARCODE_EVENT_ID


def test_fail_too_high_badges(cfg):
    with pytest.raises(ValueError) as ex:
        encrypted = generate_barcode_from_badge_num(badge_num=0xFFFFFF+1)
    assert 'either badge_number or salt is too large' in str(ex.value)


def test_fail_key_length(cfg, monkeypatch):
    monkeypatch.setattr(c, 'BARCODE_KEY', 'X')
    with pytest.raises(ValueError) as ex:
        encrypted = generate_barcode_from_badge_num(badge_num=1)
    assert 'key length should be exactly' in str(ex.value)


def test_fail_wrong_event_id(cfg, monkeypatch):
    with pytest.raises(ValueError) as ex:
        barcode = generate_barcode_from_badge_num(badge_num=1, event_id=1)
        get_badge_num_from_barcode(barcode_num=barcode, event_id=2)
    assert "doesn't match our event ID" in str(ex.value)


def test_dontfail_wrong_event_id(cfg):
    badge_num = 78946
    barcode = generate_barcode_from_badge_num(badge_num=badge_num)
    decrytped = get_badge_num_from_barcode(barcode_num=barcode, event_id=2, verify_event_id_matches=False)
    assert decrytped['badge_num'] == badge_num
    assert decrytped['event_id'] == c.BARCODE_EVENT_ID


def test_valid_barcode_character_validations(cfg):
    # some valid barcodes
    for s in ["jhgsd+", "ABMN45", "asfnb/", "912765", "++//00"]:

        # test to make sure it DOES work with prefix
        assert_is_valid_rams_barcode(c.BARCODE_PREFIX_CHAR + s)

        # test to make sure it DOES NOT work without prefix
        with pytest.raises(ValueError) as ex:
            assert_is_valid_rams_barcode(s)
        assert 'barcode validation error' in str(ex.value)


def test_invalid_barcode_character_validations(cfg):
    invalid_barcodes = [
        "^^^^^^",
        "(}(*&4", "---2hg",
        "{}{<>?",
        "      ",
        "ABCDEFGH",
        "abcdefgh",
        "1234567",
        "ffff"]
    for s in invalid_barcodes:
        # test without a prefix (shouldn't work)
        with pytest.raises(ValueError) as ex:
            assert_is_valid_rams_barcode(s)
        assert 'barcode validation error' in str(ex.value)

        # test with a prefix (still shouldn't work)
        with pytest.raises(ValueError) as ex:
            assert_is_valid_rams_barcode(c.BARCODE_PREFIX_CHAR + s)
        assert 'barcode validation error' in str(ex.value)
