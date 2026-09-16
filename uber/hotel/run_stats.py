"""Award statistics for one lottery run (the run detail page).

Three views of a run, all derived on demand from the run's RoomAssignment
rows, their applications, and the snapshot of entries the run recorded
in `LotteryRun.considered_application_ids`:

* preference rank - for every primary room the run awarded, where the
  awarded hotel and the awarded room/suite type sat in the entrant's
  ranked preference lists (#1, #2, ... or not ranked at all);
* group size - what share of awarded rooms went to 1-person, 2-person,
  ... groups, against the same distribution over every entry the run
  considered;
* demand - per hotel and per room/suite type, how many considered
  entries ranked it first (or listed it anywhere) versus how many rooms
  the run awarded there.

Group size is the leader plus their valid group members as of now - the
same rule the application form and the award emails use - applied to
both sides so the comparison is like for like. Connector rooms are not
awards in their own right and are excluded.

Read-only; never flushes or commits.
"""

from collections import Counter, defaultdict

import sqlalchemy as sa
from sqlalchemy.orm import joinedload

from uber.config import c
from uber.models import Attendee, LotteryApplication
from uber.models.hotel import LotteryHotel, LotteryRoomType, RoomAssignment

NOT_RANKED = 'Not ranked'


def _ids(csv):
    return [x.strip() for x in (csv or '').split(',') if x.strip()]


def _rank_of(csv, wanted):
    """1-based position of `wanted` in a ranked-preference CSV, or None."""
    ids = _ids(csv)
    wanted = str(wanted)
    return ids.index(wanted) + 1 if wanted in ids else None


def _type_preference(app, inv):
    """The ranked list the awarded block's type would appear in: suites
    and rooms are separate lists on the application."""
    return app.suite_type_preference if inv.is_suite else app.room_type_preference


def _pct(n, total):
    return round(100.0 * n / total, 1) if total else 0.0


def group_sizes(session, app_ids):
    """{application_id: 1 + valid group members} for every id, in one
    query. Mirrors LotteryApplication.valid_group_members: members count
    when their attendee is lottery-eligible and their entry is COMPLETE,
    REJECTED, or in an award state."""
    sizes = {aid: 1 for aid in app_ids}
    if not app_ids:
        return sizes
    rows = (session.query(LotteryApplication.parent_application_id,
                          sa.func.count(LotteryApplication.id))
            .join(LotteryApplication.attendee)
            .filter(LotteryApplication.parent_application_id.in_(list(app_ids)),
                    Attendee.hotel_lottery_eligible == True,  # noqa: E712
                    LotteryApplication.status.in_(
                        [c.COMPLETE, c.REJECTED] + c.HOTEL_LOTTERY_AWARD_STATUSES))
            .group_by(LotteryApplication.parent_application_id).all())
    for parent_id, member_count in rows:
        sizes[parent_id] = 1 + member_count
    return sizes


def _rank_rows(counter, total):
    """[{label, count, pct}] for ranks #1..#max (zeros kept so the table
    reads as a distribution), then a 'Not ranked' row when any award
    landed outside the entrant's list."""
    ranked = [r for r in counter if r is not None]
    rows = []
    for rank in range(1, (max(ranked) if ranked else 0) + 1):
        rows.append({'label': f'#{rank}', 'count': counter.get(rank, 0),
                     'pct': _pct(counter.get(rank, 0), total)})
    if counter.get(None):
        rows.append({'label': NOT_RANKED, 'count': counter[None],
                     'pct': _pct(counter[None], total)})
    return rows


def _demand_rows(names, first_choice, any_choice, awarded,
                 considered_total, award_total):
    rows = []
    for obj_id in set(first_choice) | set(any_choice) | set(awarded):
        rows.append({
            'name': names.get(obj_id, '(deleted)'),
            'first_choice': first_choice.get(obj_id, 0),
            'first_choice_pct': _pct(first_choice.get(obj_id, 0), considered_total),
            'any_choice': any_choice.get(obj_id, 0),
            'awarded': awarded.get(obj_id, 0),
            'awarded_pct': _pct(awarded.get(obj_id, 0), award_total),
        })
    rows.sort(key=lambda r: (-r['awarded'], -r['first_choice'], r['name']))
    return rows


def lottery_run_stats(session, lottery_run):
    awards = (session.query(RoomAssignment)
              .filter(RoomAssignment.lottery_run_id == lottery_run.id,
                      RoomAssignment.parent_assignment_id.is_(None),
                      RoomAssignment.lottery_application_id.isnot(None))
              .options(joinedload(RoomAssignment.lottery_application))
              .all())
    award_total = len(awards)

    hotel_ranks, type_ranks = Counter(), Counter()
    awarded_by_hotel, awarded_by_type = Counter(), Counter()
    for ra in awards:
        app, inv = ra.lottery_application, ra.inventory
        if inv is None:
            hotel_ranks[None] += 1
            type_ranks[None] += 1
            continue
        hotel_ranks[_rank_of(app.hotel_preference, inv.hotel_id)] += 1
        type_ranks[_rank_of(_type_preference(app, inv), inv.room_or_suite_type_id)] += 1
        awarded_by_hotel[str(inv.hotel_id)] += 1
        awarded_by_type[str(inv.room_or_suite_type_id)] += 1

    # Group size per awarded ROOM (an entrant with two rooms counts twice:
    # the question is what share of rooms went to groups of each size).
    awarded_app_ids = {ra.lottery_application_id for ra in awards}
    awarded_sizes = group_sizes(session, awarded_app_ids)
    awarded_size_counts = Counter(
        awarded_sizes[ra.lottery_application_id] for ra in awards)

    considered_ids = [str(x) for x in (lottery_run.considered_application_ids or [])]
    considered_total = len(considered_ids)
    considered_size_counts = Counter(group_sizes(session, considered_ids).values())

    first_hotel, any_hotel = Counter(), Counter()
    first_type, any_type = Counter(), Counter()
    if considered_ids:
        rows = session.query(
            LotteryApplication.entry_type, LotteryApplication.room_opt_out,
            LotteryApplication.hotel_preference, LotteryApplication.room_type_preference,
            LotteryApplication.suite_type_preference,
        ).filter(LotteryApplication.id.in_(considered_ids)).all()
        for entry_type, room_opt_out, hotels, room_types, suite_types in rows:
            hotel_ids = _ids(hotels)
            if hotel_ids:
                first_hotel[hotel_ids[0]] += 1
            any_hotel.update(set(hotel_ids))
            # A suite entry's primary list is suites; its room list only
            # counts when it also competes for rooms (not opted out).
            if entry_type == c.SUITE_ENTRY:
                primary, secondary = _ids(suite_types), ([] if room_opt_out else _ids(room_types))
            else:
                primary, secondary = _ids(room_types), []
            if primary:
                first_type[primary[0]] += 1
            any_type.update(set(primary) | set(secondary))

    hotel_names = {str(h.id): h.name for h in session.query(LotteryHotel).all()}
    type_names = {str(t.id): t.name for t in session.query(LotteryRoomType).all()}

    sizes = sorted(set(awarded_size_counts) | set(considered_size_counts))
    return {
        'award_count': award_total,
        'considered_count': considered_total,
        'considered_recorded': bool(considered_ids),
        'hotel_ranks': _rank_rows(hotel_ranks, award_total),
        'type_ranks': _rank_rows(type_ranks, award_total),
        'group_sizes': [{
            'size': size,
            'awarded': awarded_size_counts.get(size, 0),
            'awarded_pct': _pct(awarded_size_counts.get(size, 0), award_total),
            'considered': considered_size_counts.get(size, 0),
            'considered_pct': _pct(considered_size_counts.get(size, 0), considered_total),
        } for size in sizes],
        'hotel_demand': _demand_rows(hotel_names, first_hotel, any_hotel, awarded_by_hotel,
                                     considered_total, award_total),
        'type_demand': _demand_rows(type_names, first_type, any_type, awarded_by_type,
                                    considered_total, award_total),
    }
