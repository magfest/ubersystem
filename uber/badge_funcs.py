from uber.models import Attendee
from uber.config import c


def check_range(badge_num, badge_type):
    if badge_num is not None:
        try:
            badge_num = int(badge_num)
        except Exception:
            return '"{}" is not a valid badge number (should be an integer)'.format(badge_num)

        if badge_num:
            min_num, max_num = c.BADGE_RANGES[int(badge_type)]
            if not min_num <= badge_num <= max_num:
                return '{} badge numbers must fall within the range {} - {}'.format(
                    dict(c.BADGE_OPTS)[badge_type], min_num, max_num)


def is_badge_unchanged(attendee, old_badge_type, old_badge_num):
    old_badge_num = int(old_badge_num or 0) or None
    return old_badge_type == attendee.badge_type and (
        not attendee.badge_num or old_badge_num == attendee.badge_num)


def reset_badge_if_unchanged(attendee, old_badge_type, old_badge_num):
    """
    The "change badge" page can pass an empty string for the badge number,
    but if nothing actually changed about the attendee's badge, we need the
    old number back!
    """
    if is_badge_unchanged(attendee, old_badge_type, old_badge_num):
        attendee.badge_num = old_badge_num
        return 'Attendee is already {} with badge {}'.format(c.BADGES[old_badge_type], old_badge_num)


# TODO: returning (result, error) is not a convention we're using anywhere else,
#       so maybe change this to be more idiomatic if convenient, but not a big deal
def get_badge_type(badge_num):
    if not c.NUMBERED_BADGES:
        return c.ATTENDEE_BADGE, ''
    else:
        try:
            for (badge_type, (lowest, highest)) in c.BADGE_RANGES.items():
                if int(badge_num) in range(lowest, highest + 1):
                    return badge_type, ''
            return None, "{0!r} isn't a valid badge number; it's not in the range of any badge type".format(badge_num)
        except Exception:
            return None, '{0!r} is not a valid integer'.format(badge_num)


def get_real_badge_type(badge_type):
    return c.ATTENDEE_BADGE if badge_type in [c.PSEUDO_DEALER_BADGE, c.PSEUDO_GROUP_BADGE] else badge_type
# TODO: perhaps a check_leaderless() for checking for leaderless groups, since those don't get emails


# run through all badges and check 2 things:
# 1) there are no gaps in badge numbers
# 2) all badge numbers are in the ranges set by c.BADGE_RANGES
# note: does not do any duplicates checking, that's a different pre-existing check
def badge_consistency_check(session):
    errors = []

    # check 1, see if anything is out of range, or has a duplicate badge number
    badge_nums_seen = []

    attendees = session.query(Attendee).filter(Attendee.first_name != '', Attendee.badge_num != 0) \
        .order_by('badge_num').all()

    for attendee in attendees:
        out_of_range_error = check_range(attendee.badge_num, attendee.badge_type)
        if out_of_range_error:
            msg = '{a.full_name}: badge #{a.badge_num}: {err}'.format(a=attendee, err=out_of_range_error)
            errors.append(msg)

        if attendee.badge_num in badge_nums_seen:
            msg = '{a.full_name}: badge #{a.badge_num}: Has been assigned the same badge number ' \
                  'of another badge, which is not supposed to happen'.format(a=attendee)
            errors.append(msg)

        badge_nums_seen.append(attendee.badge_num)

    # check 2: see if there are any gaps in each of the badge ranges
    for badge_type_val, badge_type_desc in c.BADGE_OPTS:
        prev_badge_num = -1
        prev_attendee_name = ""

        attendees = session.query(Attendee) \
            .filter(Attendee.badge_type == badge_type_val, Attendee.first_name != '', Attendee.badge_num != 0) \
            .order_by('badge_num').all()

        for attendee in attendees:
            if prev_badge_num == -1:
                prev_badge_num = attendee.badge_num
                prev_attendee_name = attendee.full_name
                continue

            if attendee.badge_num - 1 != prev_badge_num:
                msg = "gap in badge sequence between " + badge_type_desc + " " + \
                      "badge# " + str(prev_badge_num) + "(" + prev_attendee_name + ")" + " and " + \
                      "badge# " + str(attendee.badge_num) + "(" + attendee.full_name + ")"

                errors.append(msg)

            prev_badge_num = attendee.badge_num
            prev_attendee_name = attendee.full_name

    return errors


def needs_badge_num(attendee=None, badge_type=None):
    """
    Takes either an Attendee object, a badge_type, or both and returns whether or not the attendee should be
    assigned a badge number. If neither parameter is given, always returns False.

    :param attendee: Passing an existing attendee allows us to check for a new badge num whenever the attendee
    is updated, particularly for when they are checked in.
    :param badge_type: Must be an integer. Allows checking for a new badge number before adding/updating the
    Attendee() object.
    :return:
    """
    if not badge_type and attendee:
        badge_type = attendee.badge_type
    elif not badge_type and not attendee:
        return None

    if c.NUMBERED_BADGES:
        if attendee:
            return (badge_type in c.PREASSIGNED_BADGE_TYPES or attendee.checked_in) \
                   and attendee.paid != c.NOT_PAID and attendee.is_valid
        else:
            return badge_type in c.PREASSIGNED_BADGE_TYPES
