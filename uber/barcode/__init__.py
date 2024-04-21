import base64
import os
import string
import struct

import uber.barcode
import uber.barcode.skip32
import uber.barcode.code128
from uber.config import c


def generate_barcode_csv(range_start, range_end):
    generated_lines = []
    seen_barcodes = set()
    for badge_num in range(range_start, range_end+1):
        barcode_num = generate_barcode_from_badge_num(badge_num=badge_num)

        line = "{badge_num},{barcode_num}{newline}".format(
            badge_num=badge_num,
            barcode_num=barcode_num,
            newline=os.linesep
        )
        generated_lines.append(line)

        # ensure that we haven't seen this value before
        # We don't expect this to ever happen, but, never hurts to be paranoid.
        if barcode_num in seen_barcodes:
            raise ValueError("COLLISION: generated a badge# that's already been seen. change barcode key, try again")

        seen_barcodes.add(barcode_num)

    return generated_lines


def generate_barcode_from_badge_num(badge_num, event_id=None, salt=None, key=None):
    event_id = event_id or c.BARCODE_EVENT_ID
    salt = salt or c.BARCODE_SALT
    key = key or bytes(c.BARCODE_KEY, 'ascii')

    if event_id > 0xFF or event_id < 0x00:
        raise ValueError('event_id needs to be between 0 and 255')

    key_len = len(key)
    if key_len != 10:
        raise ValueError('key length should be exactly 10 bytes, length={}'.format(key_len))

    # 4 bytes of data are going to be packed into an ecnrypted barcode:
    # byte 1: 1 byte event ID
    # byte 2,3,4: 24bit badge number (max of 16 million, more than reasonable)

    salted_val = badge_num + (0 if not salt else salt)

    if salted_val > 0xFFFFFF:
        raise ValueError('either badge_number or salt is too large to turn into a barcode: {}'.format(badge_num))

    # create a 5-byte result with event_id and salted_val packed in there
    data_to_encrypt = struct.pack('>BI', event_id, salted_val)

    # discard the 2nd byte of this 5 byte structure (the highest byte
    # of salted_val).  it should always be zero.
    # reduces data_to_encrypt from 5 bytes to 4 bytes.
    data_to_encrypt = bytearray([data_to_encrypt[0], data_to_encrypt[2], data_to_encrypt[3], data_to_encrypt[4]])

    if len(data_to_encrypt) != 4:
        raise ValueError("data to encrypt should be 4 bytes")

    encrypted_string = _barcode_raw_encrypt(data_to_encrypt, key=key)

    # check to make sure it worked.
    decrypted = get_badge_num_from_barcode(encrypted_string, salt, key)
    decrypted_badge_num = decrypted['badge_num']
    decrypted_event_id = decrypted['event_id']
    if decrypted_badge_num != badge_num or decrypted_event_id != event_id:
        raise ValueError("internal algorithm error: verification did not decrypt correctly")

    # check to make sure this barcode number is valid for Code 128 barcode
    assert_is_valid_rams_barcode(encrypted_string)

    return encrypted_string


def get_badge_num_from_barcode(barcode_num, salt=None, key=None, event_id=None, verify_event_id_matches=True):
    event_id = event_id or c.BARCODE_EVENT_ID
    salt = salt or c.BARCODE_SALT
    key = key or bytes(c.BARCODE_KEY, 'ascii')

    assert_is_valid_rams_barcode(barcode_num)

    decrypted = _barcode_raw_decrypt(barcode_num, key=key)

    result = dict()

    # event_id is the 1st byte of these 4 bytes
    result['event_id'] = struct.unpack('>B', bytearray([decrypted[0]]))[0]

    # salted_val is the remaining 3 bytes, and the high order byte is
    # always 0, yielding a 24bit number we unpack into a 32bit int
    badge_bytes = bytearray(bytes([0, decrypted[1], decrypted[2], decrypted[3]]))

    result['badge_num'] = struct.unpack('>I', badge_bytes)[0] - salt

    if verify_event_id_matches and result['event_id'] != event_id:
        raise ValueError('unrecognized event id: {}'.format(result['event_id']))

    return result


def verify_is_valid_rams_barcode(barcode):
    return barcode.find('=') == -1 \
        and len(barcode) == 7 \
        and barcode[0] == c.BARCODE_PREFIX_CHAR \
        and verify_is_valid_base64_charset(barcode[1:]) \
        and verify_barcode_is_valid_code128_charset(barcode[1:])


_valid_base_64_charset = tuple(string.ascii_letters) + tuple(string.digits) + ('+', '/', '=')


def verify_is_valid_base64_charset(str):
    for ch in str:
        if ch not in _valid_base_64_charset:
            return False
    return True


def verify_barcode_is_valid_code128_charset(str):
    for ch in str:
        if ch not in uber.barcode.code128._charset_b:
            return False
    return True


def assert_is_valid_rams_barcode(barcode):
    if not verify_is_valid_rams_barcode(barcode):
        raise ValueError("barcode validation error: invalid format for barcode: {}".format(barcode))


def _barcode_raw_encrypt(value, key):
    if len(value) != 4:
        raise ValueError("invalid barcode input: needs to be exactly 4 bytes")

    # skip32 generates 4 bytes output from 4 bytes input
    _encrypt = True
    uber.barcode.skip32.skip32(key, value, _encrypt)

    # Raw bytes aren't suitable for a Code 128 barcode though,
    # so convert it to base58 encoding
    # which is just some alphanumeric and numeric chars and is
    # designed to be vaguely human.
    # This takes our 4 bytes and turns it into 6 chars
    encrypted_value = base64.encodebytes(value).decode('ascii')

    # Important note: because we are not an even multiple of 3 bytes, base64
    # needs to pad the resulting string with equals signs.  We can strip them
    # out knowing that our length is 4 bytes.
    #
    # IF YOU CHANGE THE LENGTH OF THE ENCRYPTED DATA FROM 4 BYTES,
    # THIS WILL NO LONGER WORK.
    encrypted_value = encrypted_value.replace('==\n', '')

    # Pre-pend a character prefix to this barcode for easy ID
    encrypted_value = c.BARCODE_PREFIX_CHAR + encrypted_value

    if len(encrypted_value) != 7:
        raise ValueError("Barcode encryption failure: result should be 7 characters")

    return encrypted_value


def _barcode_raw_decrypt(value, key):
    # Raw bytes aren't suitable for a Code 128 barcode though,
    # so convert it to base64 encoding
    # which is just some alphanumeric and numeric chars and is
    # designed to be vaguely human.
    # This takes our 4 bytes and turns it into 6ish bytes.

    # Important note: because we are not an even multiple of 3 bytes, base64
    # needs to pad the resulting string with equals signs.  we can strip them
    # out knowing that our length is 4 bytes.
    #
    # IF YOU CHANGE THE LENGTH OF THE ENCRYPTED DATA FROM 4 BYTES,
    # THIS WILL NO LONGER WORK.

    if len(value) != 7:
        raise ValueError("Barcode decryption failure: barcode should be 7 characters")

    # strip the character prefix
    if value[0] == c.BARCODE_PREFIX_CHAR:
        value = value[1:]
        assert len(value) == 6
    else:
        raise ValueError("Barcode decryption failure: barcode should start with prefix of '{}'".format(
            c.BARCODE_PREFIX_CHAR))

    # add the base64 tail in here
    value += '==\n'

    decoded = base64.decodebytes(value.encode('ascii'))

    # skip32 generates 4 bytes output from 4 bytes input
    _encrypt = False
    decrytped = bytearray(decoded)

    try:
        uber.barcode.skip32.skip32(key, decrytped, _encrypt)
    except Exception as e:
        raise ValueError(
            "Failed to decrypt barcode: check secret_key, event_id, and whether this barcode is from this event") from e

    if len(decrytped) != 4:
        raise ValueError("Invalid barcode decryption: output result was not exactly 4 bytes")

    return decrytped
