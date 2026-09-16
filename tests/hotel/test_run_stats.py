"""Award statistics on the lottery run detail page (uber.hotel.run_stats):
preference rank of awarded rooms, group-size share of awards versus the
entries considered, and per-hotel / per-type demand versus awards."""

from uber.config import c
from uber.hotel.run_stats import NOT_RANKED, group_sizes, lottery_run_stats

from tests.hotel.factories import (N, make_application, make_assignment,
                                   make_attendee, make_hotel, make_inventory,
                                   make_room_type, make_run)


def _member(session, leader, eligible=True):
    attendee = make_attendee(session)
    if not eligible:
        attendee.badge_status = c.NOT_ATTENDING
        session.flush()
    return make_application(session, attendee, status=c.COMPLETE,
                            entry_type=c.GROUP_ENTRY,
                            parent_application_id=leader.id)


def _award(session, run, app, inv):
    return make_assignment(session, app.attendee, inv, status=c.ASSIGNED,
                           assignment_reason=c.LOTTERY_AWARD,
                           payment_type='credit_card',
                           lottery_application_id=app.id, lottery_run_id=run.id,
                           check_in=N[1], check_out=N[3])


def _world(session):
    alpha, beta = make_hotel(session, name='Alpha'), make_hotel(session, name='Beta')
    king, queen = make_room_type(session, name='King'), make_room_type(session, name='Queen')
    alpha_king = make_inventory(session, alpha, king)
    alpha_queen = make_inventory(session, alpha, queen)
    return alpha, beta, king, queen, alpha_king, alpha_queen


def _entry(session, hotels, types, entry_type=c.ROOM_ENTRY, **overrides):
    return make_application(session, make_attendee(session), status=c.COMPLETE,
                            entry_type=entry_type,
                            hotel_preference=','.join(h.id for h in hotels),
                            room_type_preference=','.join(t.id for t in types),
                            **overrides)


def test_rank_group_size_and_demand_breakdowns(session):
    alpha, beta, king, queen, alpha_king, alpha_queen = _world(session)
    run = make_run(session, status=c.LOTTERY_PENDING)

    first = _entry(session, [alpha, beta], [king, queen])   # gets Alpha/King: #1 / #1
    second = _entry(session, [beta, alpha], [queen])        # gets Alpha/Queen: #2 / #1
    third = _entry(session, [beta], [queen, king])          # gets Alpha/King: unranked / #2
    _member(session, third)
    _member(session, third)
    loser = _entry(session, [beta], [queen])                # considered, not awarded
    _member(session, loser)
    for app in (first, second, third, loser):
        app.lottery_run_id = None
    run.considered_application_ids = [first.id, second.id, third.id, loser.id]
    session.flush()

    _award(session, run, first, alpha_king)
    _award(session, run, second, alpha_queen)
    third_room = _award(session, run, third, alpha_king)
    # A connector hanging off an award is not an award of its own.
    make_assignment(session, third.attendee, alpha_queen, status=c.ASSIGNED,
                    assignment_reason=c.SUITE_CONNECTOR, payment_type='credit_card',
                    lottery_application_id=third.id, lottery_run_id=run.id,
                    parent_assignment_id=third_room.id, check_in=N[1], check_out=N[3])

    stats = lottery_run_stats(session, run)

    assert stats['award_count'] == 3
    assert stats['considered_count'] == 4
    assert stats['considered_recorded'] is True

    hotel = {r['label']: (r['count'], r['pct']) for r in stats['hotel_ranks']}
    assert hotel == {'#1': (1, 33.3), '#2': (1, 33.3), NOT_RANKED: (1, 33.3)}
    types = {r['label']: r['count'] for r in stats['type_ranks']}
    assert types == {'#1': 2, '#2': 1}

    sizes = {r['size']: r for r in stats['group_sizes']}
    assert sizes[1]['awarded'] == 2 and sizes[1]['awarded_pct'] == 66.7
    assert sizes[3]['awarded'] == 1 and sizes[3]['awarded_pct'] == 33.3
    assert sizes[1]['considered'] == 2 and sizes[1]['considered_pct'] == 50.0
    assert sizes[2]['considered'] == 1 and sizes[2]['awarded'] == 0
    assert sizes[3]['considered'] == 1

    hotels = {r['name']: r for r in stats['hotel_demand']}
    assert hotels['Alpha'] == {'name': 'Alpha', 'first_choice': 1, 'first_choice_pct': 25.0,
                               'any_choice': 2, 'awarded': 3, 'awarded_pct': 100.0}
    assert hotels['Beta']['first_choice'] == 3 and hotels['Beta']['awarded'] == 0
    assert [r['name'] for r in stats['hotel_demand']] == ['Alpha', 'Beta'], 'most awarded first'
    kinds = {r['name']: r for r in stats['type_demand']}
    assert (kinds['King']['first_choice'], kinds['King']['awarded']) == (1, 2)
    assert (kinds['Queen']['first_choice'], kinds['Queen']['any_choice'], kinds['Queen']['awarded']) == (3, 4, 1)


def test_group_size_ignores_ineligible_and_withdrawn_members(session):
    leader = _entry(session, [], [])
    _member(session, leader)
    _member(session, leader, eligible=False)
    gone = _member(session, leader)
    gone.status = c.WITHDRAWN
    session.flush()

    assert group_sizes(session, {leader.id}) == {leader.id: 2}
    assert leader.valid_group_members and len(leader.valid_group_members) == 1, \
        'matches the model property the forms and emails use'


def test_suite_entry_demand_uses_suite_list_and_optional_room_fallback(session):
    alpha, beta, king, queen, alpha_king, alpha_queen = _world(session)
    tower = make_room_type(session, name='Tower Suite', is_suite=True)
    run = make_run(session, status=c.LOTTERY_PENDING)
    in_both = _entry(session, [alpha], [king], entry_type=c.SUITE_ENTRY,
                     suite_type_preference=tower.id, room_opt_out=False)
    suite_only = _entry(session, [alpha], [king], entry_type=c.SUITE_ENTRY,
                        suite_type_preference=tower.id, room_opt_out=True)
    run.considered_application_ids = [in_both.id, suite_only.id]
    session.flush()

    kinds = {r['name']: r for r in lottery_run_stats(session, run)['type_demand']}
    assert kinds['Tower Suite']['first_choice'] == 2
    assert kinds['King']['first_choice'] == 0
    assert kinds['King']['any_choice'] == 1, 'only the entry still competing for rooms'


def test_run_without_snapshot_reports_no_comparison(session):
    alpha, beta, king, queen, alpha_king, alpha_queen = _world(session)
    run = make_run(session, status=c.LOTTERY_AWARDED)
    app = _entry(session, [alpha], [king])
    _award(session, run, app, alpha_king)

    stats = lottery_run_stats(session, run)
    assert stats['considered_recorded'] is False
    assert stats['considered_count'] == 0
    assert stats['award_count'] == 1
    assert stats['group_sizes'] == [{'size': 1, 'awarded': 1, 'awarded_pct': 100.0,
                                     'considered': 0, 'considered_pct': 0.0}]
    assert stats['hotel_demand'][0]['first_choice_pct'] == 0.0


def test_empty_run(session):
    run = make_run(session, status=c.LOTTERY_REVERTED)
    stats = lottery_run_stats(session, run)
    assert stats['award_count'] == 0
    assert stats['hotel_ranks'] == [] and stats['type_ranks'] == []
    assert stats['group_sizes'] == []
