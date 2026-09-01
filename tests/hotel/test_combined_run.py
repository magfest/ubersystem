"""The combined room-plus-suite lottery run."""

from datetime import date

import pytest

from uber.config import c
from uber.hotel.solver import (LOTTERY_TYPE_BOTH, MAX_PREFERENCE_RANK,
                               SUITE_TIER_BONUS, _entry_preferences, _rank_map,
                               solve_lottery, weight_entry)


N1 = date(2027, 1, 7)
N3 = date(2027, 1, 10)


class _App:
    """The handful of attributes the solver reads off an application."""
    def __init__(self, id, entry_type, hotels='', room_types='', suite_types='',
                 room_opt_out=False):
        self.id = id
        self.entry_type = entry_type
        self.hotel_preference = hotels
        self.room_type_preference = room_types
        self.suite_type_preference = suite_types
        self.room_opt_out = room_opt_out
        self.parent_application = None
        self.earliest_checkin_date = N1
        self.latest_checkout_date = N3


def _block(id, room_type, hotel='h1', quantity=1):
    return {'id': id, 'hotel_id': hotel, 'room_type': room_type,
            'capacity': 4, 'min_capacity': 1, 'quantity': quantity,
            'night_quantities': {}}


# ---------------------------------------------------------------------------
# rank maps
# ---------------------------------------------------------------------------

def test_rank_map_scores_best_choice_highest():
    ranks = _rank_map(['a', 'b', 'c'])
    assert ranks['a'] > ranks['b'] > ranks['c']


def test_rank_map_clamps_at_zero_past_ten_choices():
    """Ranking more than ten options used to raise; it now just bottoms out."""
    ranks = _rank_map([str(n) for n in range(15)])
    assert min(ranks.values()) == 0


def test_rank_map_tiers_primary_above_fallback():
    ranks = _rank_map(['suite'], ['room'], tier_bonus=SUITE_TIER_BONUS)
    assert ranks['suite'] > ranks['room']


def test_rank_map_keeps_the_primary_score_for_a_shared_id():
    ranks = _rank_map(['x'], ['x'], tier_bonus=SUITE_TIER_BONUS)
    assert ranks['x'] == SUITE_TIER_BONUS + 10


# ---------------------------------------------------------------------------
# which preferences enter a run
# ---------------------------------------------------------------------------

def test_combined_run_gives_suite_entries_a_room_fallback():
    app = _App('a', c.SUITE_ENTRY, room_types='r1', suite_types='s1')
    assert _entry_preferences(app, LOTTERY_TYPE_BOTH) == (['s1'], ['r1'], SUITE_TIER_BONUS)


@pytest.mark.parametrize('room_opt_out', [True, None])
def test_combined_run_honors_room_opt_out(room_opt_out):
    app = _App('a', c.SUITE_ENTRY, room_types='r1', suite_types='s1',
               room_opt_out=room_opt_out)
    assert _entry_preferences(app, LOTTERY_TYPE_BOTH) == (['s1'], [], SUITE_TIER_BONUS)


def test_combined_run_leaves_room_entries_on_rooms_only():
    app = _App('a', c.ROOM_ENTRY, room_types='r1', suite_types='s1')
    assert _entry_preferences(app, LOTTERY_TYPE_BOTH) == (['r1'], [], 0)


def test_single_type_runs_are_unchanged():
    room_app = _App('a', c.ROOM_ENTRY, room_types='r1')
    suite_app = _App('b', c.SUITE_ENTRY, suite_types='s1', room_types='r1')

    assert _entry_preferences(room_app, c.ROOM_ENTRY) == (['r1'], [], 0)
    assert _entry_preferences(suite_app, c.SUITE_ENTRY) == (['s1'], [], 0)
    # A suite entry that has not opted out still falls into a room-only run.
    assert _entry_preferences(suite_app, c.ROOM_ENTRY) == (['r1'], [], 0)
    assert _entry_preferences(room_app, c.SUITE_ENTRY) is None


@pytest.mark.parametrize('room_opt_out', [True, None])
def test_opted_out_suite_entry_stays_out_of_a_room_run(room_opt_out):
    app = _App('a', c.SUITE_ENTRY, room_types='r1', suite_types='s1',
               room_opt_out=room_opt_out)
    assert _entry_preferences(app, c.ROOM_ENTRY) is None


# ---------------------------------------------------------------------------
# weighting
# ---------------------------------------------------------------------------

def test_suite_option_outscores_room_fallback_for_one_entrant():
    entry = {
        'hotels': ['h1'],
        'hotel_ranks': _rank_map(['h1']),
        'type_ranks': _rank_map(['s1'], ['r1'], tier_bonus=SUITE_TIER_BONUS),
    }
    suite = weight_entry(entry, _block('i1', 's1'), 0)
    room = weight_entry(entry, _block('i2', 'r1'), 0)
    assert suite > room


def test_tier_bonus_is_uniform_across_suite_entrants():
    """An opted-out suite entrant scores a suite exactly like one with room
    fallbacks."""
    with_fallback = _App('a', c.SUITE_ENTRY, room_types='r1', suite_types='s1')
    opted_out = _App('b', c.SUITE_ENTRY, room_types='r1', suite_types='s1',
                     room_opt_out=True)

    ranks = {}
    for app in (with_fallback, opted_out):
        primary, fallback, tier_bonus = _entry_preferences(app, LOTTERY_TYPE_BOTH)
        ranks[app.id] = _rank_map(primary, fallback, tier_bonus=tier_bonus)

    assert ranks['a']['s1'] == ranks['b']['s1'] == SUITE_TIER_BONUS + MAX_PREFERENCE_RANK


# ---------------------------------------------------------------------------
# solving
# ---------------------------------------------------------------------------

def test_combined_run_awards_across_both_pools():
    room_app = _App('room-app', c.ROOM_ENTRY, hotels='h1', room_types='r1')
    suite_app = _App('suite-app', c.SUITE_ENTRY, hotels='h1',
                     room_types='r1', suite_types='s1')
    blocks = [_block('room-block', 'r1'), _block('suite-block', 's1')]

    allocations = solve_lottery([room_app, suite_app], blocks,
                                lottery_type=LOTTERY_TYPE_BOTH)
    awarded = {app_id: inv_id for app_id, inv_id, role in allocations
               if role == 'primary'}
    assert awarded['suite-app'] == 'suite-block'
    assert awarded['room-app'] == 'room-block'


def test_one_entrant_never_wins_both_a_suite_and_a_room():
    suite_app = _App('suite-app', c.SUITE_ENTRY, hotels='h1',
                     room_types='r1', suite_types='s1')
    blocks = [_block('room-block', 'r1'), _block('suite-block', 's1')]

    allocations = solve_lottery([suite_app], blocks, lottery_type=LOTTERY_TYPE_BOTH)
    primaries = [a for a in allocations if a[2] == 'primary']
    assert len(primaries) == 1
    assert primaries[0][1] == 'suite-block'


def test_suite_entrant_falls_back_to_a_room_when_suites_are_gone():
    suite_app = _App('suite-app', c.SUITE_ENTRY, hotels='h1',
                     room_types='r1', suite_types='s1')
    blocks = [_block('room-block', 'r1')]

    allocations = solve_lottery([suite_app], blocks, lottery_type=LOTTERY_TYPE_BOTH)
    primaries = [a for a in allocations if a[2] == 'primary']
    assert len(primaries) == 1
    assert primaries[0][1] == 'room-block'


def test_opted_out_suite_entrant_takes_no_room_in_a_combined_run():
    suite_app = _App('suite-app', c.SUITE_ENTRY, hotels='h1',
                     room_types='r1', suite_types='s1', room_opt_out=True)
    blocks = [_block('room-block', 'r1')]

    allocations = solve_lottery([suite_app], blocks, lottery_type=LOTTERY_TYPE_BOTH)
    assert [a for a in allocations if a[2] == 'primary'] == []
