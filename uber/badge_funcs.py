from uber.models import Attendee
from uber.config import c


def get_real_badge_type(badge_type):
    return c.ATTENDEE_BADGE if badge_type in [c.PSEUDO_DEALER_BADGE, c.PSEUDO_GROUP_BADGE] else badge_type


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
            return (badge_type in c.PREASSIGNED_BADGE_TYPES or attendee.has_personalized_badge
                    ) and (not attendee.is_unassigned or attendee.badge_type == c.CONTRACTOR_BADGE
                           ) and attendee.paid != c.NOT_PAID and attendee.is_valid
        else:
            return badge_type in c.PREASSIGNED_BADGE_TYPES
