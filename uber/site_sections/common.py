import json
import math
import re
from datetime import datetime, timedelta
from functools import wraps
from io import BytesIO

import cherrypy
import treepoem
from pockets import listify
from pytz import UTC
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import joinedload

from uber.config import c
from uber.decorators import ajax, all_renderable, check_for_encrypted_badge_num, check_if_can_reg, credit_card, \
    csrf_protected, department_id_adapter, log_pageview, site_mappable, public
from uber.errors import HTTPRedirect
from uber.models import ArbitraryCharge, Attendee, Department, Email, Group, Job, MerchDiscount, MerchPickup, \
    MPointsForCash, NoShirt, OldMPointExchange, PageViewTracking, PromoCodeGroup, Sale, Session, Shift, Tracking, \
    WatchList
from uber.utils import add_opt, check, check_csrf, check_pii_consent, Charge, get_page, hour_day_format, \
    localized_now, Order


def pre_checkin_check(attendee, group):
    if c.NUMBERED_BADGES:
        min_badge, max_badge = c.BADGE_RANGES[attendee.badge_type]
        if not attendee.badge_num:
            return 'Badge number is required'
        elif not (min_badge <= int(attendee.badge_num) <= max_badge):
            return ('{a.full_name} has a {a.badge_type_label} badge, but '
                    '{a.badge_num} is not a valid number for '
                    '{a.badge_type_label} badges').format(a=attendee)

    if c.COLLECT_EXACT_BIRTHDATE:
        if not attendee.birthdate:
            return 'You may not check someone in without a valid date of birth.'
    elif not attendee.age_group or attendee.age_group == c.AGE_UNKNOWN:
        return 'You may not check someone in without confirming their age.'

    if attendee.checked_in:
        return attendee.full_name + ' was already checked in!'

    if group and attendee.paid == c.PAID_BY_GROUP and group.amount_unpaid:
        return 'This attendee\'s group has an outstanding balance of ${}'.format('%0.2f' % group.amount_unpaid)

    if attendee.paid == c.NOT_PAID:
        return 'You cannot check in an attendee that has not paid.'

    return check(attendee)


def check_atd(func):
    @wraps(func)
    def checking_at_the_door(self, *args, **kwargs):
        if c.AT_THE_CON or c.DEV_BOX:
            return func(self, *args, **kwargs)
        else:
            raise HTTPRedirect('index')
    return checking_at_the_door


@all_renderable()
class Root:
    def index(self, session, message='', page='0', search_text='', uploaded_id='', order='last_first', invalid=''):
        pass