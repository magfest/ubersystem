"""uber.hotel.exports booking serialization: the canonical booking_dict
shape, the guests/effective-occupants logic, and the spreadsheet layout
(which must never leak the vault token)."""

from uber.config import c
from uber.hotel.exports import (booking_columns, booking_dict,
                                booking_export_data, booking_row)

from tests.hotel.factories import (N, make_application, make_assignment,
                                   make_attendee, make_hotel, make_inventory,
                                   make_room_type)

CANONICAL_KEYS = {
    'assignment_id', 'lottery_application_id', 'parent_assignment_id',
    'confirmation_num', 'response_id', 'assignment_reason', 'status',
    'hotel', 'hotel_id', 'room_type', 'suite_type',
    'check_in_date', 'check_out_date', 'num_nights',
    'hotel_confirmation_number', 'cancellation_confirmation_number',
    'room_number', 'legal_first_name', 'legal_last_name', 'cellphone',
    'email', 'address1', 'address2', 'city', 'region', 'zip_code',
    'country', 'wants_ada', 'ada_requests', 'special_requests',
    'hotel_rewards_number', 'payment_type', 'payment_code',
    'num_occupants', 'guests',
    'cc_token', 'cc_last_four', 'cc_card_type', 'cc_card_expiry',
    'cc_card_holder', 'last_modified_at', 'cc_captured_at',
}

DROPPED_ALIASES = {
    'room_id', 'hotel_cancellation_number', 'last_modified',
    'assigned_hotel', 'assigned_hotel_id', 'assigned_room_type',
    'assigned_suite_type', 'assigned_check_in_date',
    'assigned_check_out_date',
    # Superseded by payment_type / payment_code, which can also say whether
    # parking is covered.
    'require_cc',
}


def _booking(session, **assignment_overrides):
    hotel = make_hotel(session, name='Serializer Test Hotel')
    room_type = make_room_type(session, name='Serializer Standard')
    inv = make_inventory(session, hotel, room_type=room_type, quantity=5)
    attendee = make_attendee(session, first='Booker', last='Person')
    app = make_application(session, attendee, cellphone='5555550001',
                           wants_ada=False)
    ra = make_assignment(session, attendee, inv, status=c.SECURED,
                         check_in=N[1], check_out=N[3],
                         lottery_application_id=app.id,
                         cc_token='vault-token-secret', cc_last_four='4242',
                         cc_card_type='Visa',
                         address1='123 Test St', city='Rockville',
                         region='MD', zip_code='20850',
                         country='United States',
                         **assignment_overrides)
    return hotel, inv, attendee, app, ra


def test_booking_dict_canonical_keys_and_dropped_aliases(session):
    hotel, inv, attendee, app, ra = _booking(session)

    d = booking_dict(ra, app)

    assert set(d) == CANONICAL_KEYS
    assert not DROPPED_ALIASES & set(d), \
        'legacy double-emitted alias keys must stay gone'
    assert d['assignment_id'] == ra.id
    assert d['hotel'] == 'Serializer Test Hotel'
    assert d['room_type'] == 'Serializer Standard'
    assert d['suite_type'] is None
    assert d['check_in_date'] == N[1].isoformat()
    assert d['check_out_date'] == N[3].isoformat()
    assert d['num_nights'] == 2
    assert d['cc_token'] == 'vault-token-secret'


def test_booking_dict_guests_from_managed_occupants(session):
    _, _, attendee, app, ra = _booking(session)

    # The creation flush ran ensure_booker_is_occupant, so the managed
    # occupants list is [booker]: guests excludes the booker.
    d = booking_dict(ra, app)
    assert d['guests'] == []
    assert d['num_occupants'] == 1


def test_booking_dict_guests_group_member_fallback(session):
    _, _, attendee, app, ra = _booking(session)

    member_attendee = make_attendee(session, first='Roomie', last='Member')
    make_application(session, member_attendee, status=c.COMPLETE,
                     entry_type=c.GROUP_ENTRY,
                     parent_application_id=app.id)

    # Simulate a row with no managed occupants (pre-dating the booker
    # presave, or an import): clear the association in-session and read
    # before any flush re-adds the booker.
    ra.occupants.clear()
    assert not ra.occupants

    d = booking_dict(ra, app)
    assert d['num_occupants'] == 2
    assert len(d['guests']) == 1, \
        'no-occupants rows fall back to booker + valid group members'
    guest = d['guests'][0]
    assert guest['legal_first_name'] == 'Roomie'
    assert guest['legal_last_name'] == 'Member'
    assert all(set(g) == {'legal_first_name', 'legal_last_name',
                          'cellphone', 'email'} for g in d['guests'])


def test_booking_row_and_export_layout(session):
    hotel, inv, attendee, app, ra = _booking(session)

    row = booking_row(ra, app)
    from uber.hotel.exports import BOOKING_BASE_COLS
    assert len(row) == len(BOOKING_BASE_COLS)
    assert 'vault-token-secret' not in row, \
        'the vault token must never appear in a spreadsheet row'
    assert '4242' in row  # cc_last_four IS allowed

    result_hotel, rows = booking_export_data(session, hotel.id)
    assert result_hotel.id == hotel.id
    assert len(rows) == 1
    full_row = rows[0]
    assert len(full_row) == len(booking_columns()), \
        'spreadsheet row width must match the header layout'
    assert 'vault-token-secret' not in full_row


def test_booking_export_data_unknown_hotel(session):
    import uuid
    result_hotel, rows = booking_export_data(session, str(uuid.uuid4()))
    assert result_hotel is None
    assert rows == []
