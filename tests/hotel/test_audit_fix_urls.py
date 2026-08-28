"""Every room issue must lead somewhere an admin can actually act."""

from datetime import date

import pytest

from uber.config import c
from uber.hotel.audit import annotate_issues, collect_issues, _fix_url_for

from tests.hotel.factories import (make_assignment, make_attendee, make_hotel,
                                   make_inventory, make_partition,
                                   make_partition_block, make_room_type)


def _annotated(session):
    room_issues, inv_issues = collect_issues(session)
    annotate_issues(room_issues, {})
    annotate_issues(inv_issues, {})
    return room_issues, inv_issues


def _by_kind(issues, kind):
    return [i for i in issues if i['kind'] == kind]


def test_manual_room_still_gets_a_link(session, no_cherrypy_session):
    """The original complaint: an under-capacity manual room had no
    application, so it got no fix link at all."""
    hotel = make_hotel(session)
    inv = make_inventory(session, hotel, capacity=4, min_capacity=3)
    attendee = make_attendee(session)
    ra = make_assignment(session, attendee=attendee, inventory=inv,
                         check_in=date(2027, 1, 7), check_out=date(2027, 1, 10))
    assert ra.lottery_application_id is None
    session.flush()

    room_issues, _ = _annotated(session)
    under = _by_kind(room_issues, 'under_capacity')
    assert under, 'expected an under_capacity issue'
    issue = under[0]

    assert issue['fixes'], 'every issue needs at least one fix target'
    assert issue['fix_url']
    # The block is where min_capacity lives, so it leads.
    assert issue['fixes'][0]['label'] == 'Edit inventory block'
    assert str(inv.id) in issue['fixes'][0]['url']
    # The room itself is still reachable.
    assert any('edit_room_assignment' in f['url'] for f in issue['fixes'])


def test_fix_url_falls_back_to_the_assignment_editor(session, no_cherrypy_session):
    hotel = make_hotel(session)
    inv = make_inventory(session, hotel)
    attendee = make_attendee(session)
    ra = make_assignment(session, attendee=attendee, inventory=inv)
    session.flush()

    assert _fix_url_for(ra) == f'edit_room_assignment?id={ra.id}'


def test_every_issue_has_a_usable_fix(session, no_cherrypy_session):
    """Build a deliberately broken set of rooms and assert nothing comes back
    unactionable."""
    hotel = make_hotel(session)
    room_type = make_room_type(session)
    inv = make_inventory(session, hotel, room_type=room_type,
                         quantity=1, capacity=2, min_capacity=2)
    partition = make_partition(session)
    make_partition_block(session, partition, inv, quantity=5)  # over-allocated

    for _ in range(3):  # oversubscribe the single-room block
        make_assignment(session, attendee=make_attendee(session), inventory=inv,
                        check_in=date(2027, 1, 7), check_out=date(2027, 1, 10))

    # A room with no dates at all.
    make_assignment(session, attendee=make_attendee(session), inventory=inv,
                    check_in=None, check_out=None)
    session.flush()

    room_issues, inv_issues = _annotated(session)
    assert room_issues or inv_issues, 'expected this setup to produce issues'

    for issue in room_issues + inv_issues:
        assert issue['fixes'], f"{issue['kind']} has no fix target"
        for fix in issue['fixes']:
            assert fix['label'], f"{issue['kind']} has an unlabelled fix"
            assert fix['url'] and '?' in fix['url'] or fix['url'].isalpha() \
                or '_' in fix['url'], f"{issue['kind']} has a malformed url: {fix['url']}"
        assert issue['fix_url'] == issue['fixes'][0]['url']


def test_double_booking_links_both_rooms(session, no_cherrypy_session):
    hotel = make_hotel(session)
    inv = make_inventory(session, hotel, quantity=10, capacity=4, min_capacity=1)
    attendee = make_attendee(session)
    first = make_assignment(session, attendee=attendee, inventory=inv,
                            check_in=date(2027, 1, 7), check_out=date(2027, 1, 10))
    second = make_assignment(session, attendee=attendee, inventory=inv,
                             check_in=date(2027, 1, 8), check_out=date(2027, 1, 11))
    # The check keys on the occupants M2M, not the booker, since one person
    # may book several rooms but cannot sleep in two on the same night.
    first.occupants.append(attendee)
    second.occupants.append(attendee)
    session.flush()

    room_issues, _ = _annotated(session)
    doubles = _by_kind(room_issues, 'double_booked')
    assert doubles, 'expected a double_booked issue'

    urls = ' '.join(f['url'] for f in doubles[0]['fixes'])
    assert str(first.id) in urls
    assert str(second.id) in urls, 'the conflicting room must be reachable too'
