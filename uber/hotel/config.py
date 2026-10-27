"""Stores settings for the hotel lottery in the DB rather than config files.
Allows admins to show and hide stuff without restarting the server.
"""
from datetime import date, datetime, time

from uber.config import c, DatabaseConfigSection

GROUPS = ('attendee', 'staff')


class LotteryGroupSettings:
    """One lottery group's settings. The tri-state values are None when the
    lottery should follow its configured dates."""
    def __init__(self, lottery_group, accept_entries=None, allow_edits=None,
                 show_closed=None, show_losses=False):
        self.lottery_group = lottery_group
        self.accept_entries = accept_entries
        self.allow_edits = allow_edits
        self.show_closed = show_closed
        self.show_losses = show_losses

    @property
    def in_window(self):
        if self.lottery_group == 'staff':
            return c.STAFF_HOTEL_LOTTERY_IN_WINDOW
        return c.HOTEL_LOTTERY_IN_WINDOW

    @property
    def accepting_entries(self):
        return self.in_window if self.accept_entries is None else self.accept_entries

    def edits_open(self, late_run_open=False):
        if self.allow_edits is not None:
            return self.allow_edits
        return self.accepting_entries or late_run_open

    def shows_closed(self, late_run_open=False):
        if self.show_closed is not None:
            return self.show_closed
        return not self.edits_open(late_run_open)


def end_of_event_day(value):
    """11:59pm event time on an ISO date string, or None when blank. Matches
    how a [dates] config entry with no time is read."""
    if not value:
        return None
    return c.EVENT_TIMEZONE.localize(datetime.combine(date.fromisoformat(value), time(23, 59)))


class HotelLotterySettings:
    """The loaded section: index by lottery group for per-group settings."""
    def __init__(self, groups, room_changes_locked=False, partition_guarantee_due=''):
        self.groups = groups
        self.room_changes_locked = room_changes_locked
        self.partition_guarantee_due_text = partition_guarantee_due
        self.partition_guarantee_due = end_of_event_day(partition_guarantee_due)

    def __getitem__(self, lottery_group):
        return self.groups[lottery_group]


class HotelLotteryConfig(DatabaseConfigSection):
    section_name = 'hotel_lottery'
    version = 1
    defaults = {
        **{group: {'accept_entries': None, 'allow_edits': None,
                   'show_closed': None, 'show_losses': False}
           for group in GROUPS},
        # Makes every attendee's and staffer's rooms view-only.
        'room_changes_locked': False,
        # ISO date shown as the card deadline in partition room emails. It is
        # display only, unlike the lottery deadline: nothing expires on it, and
        # Hotel Dept follows up on rooms still missing a card by hand.
        'partition_guarantee_due': '',
    }

    def build(self, data):
        return HotelLotterySettings(
            {group: LotteryGroupSettings(group, **data[group]) for group in GROUPS},
            room_changes_locked=data['room_changes_locked'],
            partition_guarantee_due=data['partition_guarantee_due'])


hotel_lottery_config = HotelLotteryConfig()


def late_run_open(session, lottery_group):
    """True while a pending LotteryRun for this group has apply_cutoff=False:
    the admin opened a late round that accepts changes past the deadline."""
    from uber.models.hotel import LotteryRun  # uber.models.hotel imports this module

    return session.query(LotteryRun).filter(
        LotteryRun.lottery_group == lottery_group,
        LotteryRun.apply_cutoff == False,  # noqa: E712
        LotteryRun.status == c.LOTTERY_PENDING,
    ).first() is not None
