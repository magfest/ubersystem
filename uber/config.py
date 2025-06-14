import ast
import csv
import hashlib
import inspect
import math
import os
import pycountry
import pytz
import re
import redis
import six
import yaml
import json
import uuid
import threading
import logging
import functools
import validate
import configobj
import pathlib
from tempfile import NamedTemporaryFile
from copy import deepcopy
from collections import defaultdict, OrderedDict
from datetime import date, datetime, time, timedelta
from hashlib import sha512
from markupsafe import Markup
from itertools import chain

import cherrypy
import signnow_python_sdk
from pockets import nesteddefaultdict, unwrap, cached_property
from pockets.autolog import log
from sqlalchemy import or_, func
from sqlalchemy.orm import joinedload, subqueryload

import uber

plugins_dir = pathlib.Path(__file__).parents[1] / "plugins"

def reset_threadlocal():
    threadlocal.reset(username=cherrypy.session.get("username"))

cherrypy.tools.reset_threadlocal = cherrypy.Tool('before_handler', reset_threadlocal, priority=51)
cherrypy.config.update({"tools.reset_threadlocal.on": True})

class threadlocal(object):
    """
    This class exposes a dict-like interface on top of the threading.local
    utility class; the "get", "set", "setdefault", and "clear" methods work the
    same as for a dict except that each thread gets its own keys and values.

    Ubersystem clears out all existing values and then initializes some specific
    values in the following situations:

    1) CherryPy page handlers have the 'username' key set to whatever value is
        returned by cherrypy.session['username'].

    2) Service methods called via JSON-RPC have the following two fields set:
        -> username: as above
        -> websocket_client: if the JSON-RPC request has a "websocket_client"
            field, it's value is set here; this is used internally as the
            "originating_client" value in notify() and plugins can ignore this

    3) Service methods called via websocket have the following three fields set:
        -> username: as above
        -> websocket: the WebSocketDispatcher instance receiving the RPC call
        -> message: the RPC request body; this is present on the initial call
            but not on subscription triggers in the broadcast thread
    """
    _threadlocal = threading.local()

    @classmethod
    def get(cls, key, default=None):
        return getattr(cls._threadlocal, key, default)

    @classmethod
    def set(cls, key, val):
        return setattr(cls._threadlocal, key, val)

    @classmethod
    def setdefault(cls, key, val):
        val = cls.get(key, val)
        cls.set(key, val)
        return val

    @classmethod
    def clear(cls):
        cls._threadlocal.__dict__.clear()

    @classmethod
    def get_client(cls):
        """
        If called as part of an initial websocket RPC request, this returns the
        client id if one exists, and otherwise returns None.  Plugins probably
        shouldn't need to call this method themselves.
        """
        return cls.get('client') or cls.get('message', {}).get('client')

    @classmethod
    def reset(cls, **kwargs):
        """
        Plugins should never call this method directly without a good reason; it
        clears out all existing values and replaces them with the key-value
        pairs passed as keyword arguments to this function.
        """
        cls.clear()
        for key, val in kwargs.items():
            cls.set(key, val)

def dynamic(func):
    setattr(func, '_dynamic', True)
    return func

def request_cached_property(func):
    """
    Sometimes we want a property to be cached for the duration of a request,
    with concurrent requests each having their own cached version.  This does
    that via the threadlocal class, such that each HTTP request CherryPy serves
    and each RPC request served via JSON-RPC will have its own
    cached value, which is cleared and then re-generated on later requests.
    """
    name = func.__module__ + '.' + func.__name__

    @property
    @functools.wraps(func)
    def with_caching(self):
        val = threadlocal.get(name)
        if val is None:
            val = func(self)
            threadlocal.set(name, val)
        return val
    return with_caching

def create_namespace_uuid(s):
    return uuid.UUID(hashlib.sha1(s.encode('utf-8')).hexdigest()[:32])


def really_past_mivs_deadline(deadline):
    return uber.utils.localized_now() > (deadline + timedelta(minutes=c.MIVS_SUBMISSION_GRACE_PERIOD))


class _Overridable:
    "Base class we extend below to allow plugins to add/override config options."
    @classmethod
    def mixin(cls, klass):
        for attr in dir(klass):
            if not attr.startswith('_'):
                setattr(cls, attr, getattr(klass, attr))
        return cls

    def include_plugin_config(self, plugin_config):
        """Plugins call this method to merge their own config into the global c object."""

        for attr, val in plugin_config.items():
            if not isinstance(val, dict):
                setattr(self, attr.upper(), val)

        if 'enums' in plugin_config:
            self.make_enums(plugin_config['enums'])

        if 'integer_enums' in plugin_config:
            self.make_integer_enums(plugin_config['integer_enums'])

        if 'dates' in plugin_config:
            self.make_dates(plugin_config['dates'])

        if 'data_dirs' in plugin_config:
            self.make_data_dirs(plugin_config['data_dirs'])

        if 'secret' in plugin_config:
            for attr, val in plugin_config['secret'].items():
                if not isinstance(val, dict):
                    setattr(self, attr.upper(), val)

    def make_dates(self, config_section):
        """
        Plugins can define a [dates] section in their config to create their
        own deadlines on the global c object.  This method is called automatically
        by c.include_plugin_config() if a "[dates]" section exists.
        """
        for _opt, _val in config_section.items():
            if not _val:
                _dt = None
            elif ' ' in _val:
                if ':' in _val:
                    _dt = self.EVENT_TIMEZONE.localize(datetime.strptime(_val, '%Y-%m-%d %H:%M'))
                else:
                    _dt = self.EVENT_TIMEZONE.localize(datetime.strptime(_val, '%Y-%m-%d %H'))
            else:
                _dt = self.EVENT_TIMEZONE.localize(datetime.strptime(_val + ' 23:59', '%Y-%m-%d %H:%M'))
            setattr(self, _opt.upper(), _dt)
            if _dt:
                self.DATES[_opt.upper()] = _dt

    def make_data_dirs(self, config_section):
        """
        Plugins can define a [data_dirs] section in their config to create their
        own data directories on the global c object. Data directories are
        automatically created on server startup.  This method is called automatically
        by c.include_plugin_config() if a "[data_dirs]" section exists.
        """
        for _opt, _val in config_section.items():
            setattr(self, _opt.upper(), _val)
            self.DATA_DIRS[_opt.upper()] = _val

    def make_enums(self, config_section):
        """
        Plugins can define an [enums] section in their config to create their
        own enums on the global c object.  This method is called automatically
        by c.include_plugin_config() if an "[enums]" section exists.
        """
        for name, subsection in config_section.items():
            self.make_enum(name, subsection)

    def make_integer_enums(self, config_section):
        def is_intstr(s):
            if not isinstance(s, six.string_types):
                return isinstance(s, int)
            if s and s[0] in ('-', '+'):
                return str(s[1:]).isdigit()
            return str(s).isdigit()

        for name, val in config_section.items():
            if isinstance(val, int):
                setattr(c, name.upper(), val)

        for name, section in config_section.items():
            if isinstance(section, dict):
                interpolated = OrderedDict()
                for desc, val in section.items():
                    if is_intstr(val):
                        price = int(val)
                    else:
                        price = getattr(c, val.upper())

                    interpolated[desc] = price

                c.make_enum(name, interpolated, prices=name.endswith('_price'))

    def make_enum(self, enum_name, section, prices=False):
        """
        Plugins can call this to define individual enums, or call the make_enums
        function to make all enums defined there.  See the [enums] section in
        configspec.ini file, which explains what fields are added to the global
        c object for each enum.
        """
        opts, lookup, varnames = [], {}, []
        for name, desc in section.items():
            if isinstance(desc, int):
                val, desc = desc, name
            else:
                varnames.append(name.upper())
                val = self.create_enum_val(name)

            if desc:
                opts.append((val, desc))
                if prices:
                    lookup[desc] = val
                else:
                    lookup[val] = desc

        enum_name = enum_name.upper()
        setattr(self, enum_name + '_OPTS', opts)
        setattr(self, enum_name + '_VARS', varnames)
        setattr(self, enum_name + ('' if enum_name.endswith('S') else 'S'), lookup)

    def create_enum_val(self, name):
        val = int(sha512(name.upper().encode()).hexdigest()[:7], 16)
        setattr(self, name.upper(), val)
        return val


class Config(_Overridable):
    """
    We have two types of configuration.  One is the values which come directly from our config file, such
    as the name of our event.  The other is things which depend on the date/time (such as the badge price,
    which can change over time), or whether we've hit our configured attendance cap (which changes based
    on the state of the database).  See the comments in configspec.ini for explanations of the particilar
    options, which are documented there.

    This class has a single global instance called "c" which contains values of either type of config, e.g.
    if you need to check whether dealer registration is open in your code, you'd say c.DEALER_REG_OPEN
    For all of the datetime config options, we also define BEFORE_ and AFTER_ properties, e.g. you can
    check the booleans returned by c.BEFORE_PLACEHOLDER_DEADLINE or c.AFTER_PLACEHOLDER_DEADLINE
    """
    def get_oneday_price(self, dt):
        return self.BADGE_PRICES['single_day'].get(dt.strftime('%A'), self.DEFAULT_SINGLE_DAY)

    def get_presold_oneday_price(self, badge_type):
        return self.BADGE_PRICES['single_day'].get(self.BADGES[badge_type], self.DEFAULT_SINGLE_DAY)

    def get_attendee_price(self, dt=None):
        price = self.INITIAL_ATTENDEE
        if self.PRICE_BUMPS_ENABLED:
            localized_now = uber.utils.localized_now()
            for day, bumped_price in sorted(self.PRICE_BUMPS.items()):
                if (dt or localized_now) >= day:
                    price = bumped_price

            # Only check bucket-based pricing if we're not checking an existing badge AND
            # we're not on-site (because on-site pricing doesn't involve checking badges sold)
            if not dt and not c.AT_THE_CON and self.PRICE_LIMITS:
                badges_sold = self.BADGES_SOLD

                for badge_cap, bumped_price in sorted(self.PRICE_LIMITS.items()):
                    if badges_sold >= badge_cap and bumped_price > price:
                        price = bumped_price
        return price

    def get_group_price(self, dt=None):
        return self.get_attendee_price(dt) - self.GROUP_DISCOUNT

    def get_table_price(self, table_count):
        return sum(c.TABLE_PRICES[i] for i in range(1, 1 + int(float(table_count))))

    def get_badge_count_by_type(self, badge_type):
        """
        Returns the count of all badges of the given type that we've promised to
        attendees.  This counts uncompleted placeholder badges but NOT unpaid
        badges, since those have by definition not been promised to anyone.
        """
        from uber.models import Session, Attendee
        count = 0
        with Session() as session:
            count = session.query(Attendee).filter(
                Attendee.paid != c.NOT_PAID,
                Attendee.badge_type == badge_type,
                Attendee.has_badge == True).count()  # noqa: E712
        return count

    def has_section_or_page_access(self, include_read_only=False, page_path=''):
        access = uber.models.AdminAccount.get_access_set(include_read_only=include_read_only)
        page_path = page_path or self.PAGE_PATH

        section = page_path.replace(page_path.split('/')[-1], '').strip('/')

        section_and_page = page_path.strip('/').replace('/', '_')
        if page_path.endswith('/'):
            section_and_page += "_index"

        if section_and_page in access or section in access:
            return True

        if section == 'group_admin' and any(x in access for x in ['dealer_admin', 'guest_admin',
                                                                  'band_admin', 'mivs_admin']):
            return True
        
    def update_name_problems(self):
        c.PROBLEM_NAMES = {}
        file_loc = os.path.join(c.UPLOADED_FILES_DIR, 'problem_names.csv')
        try:
            result = csv.DictReader(open(file_loc))
        except FileNotFoundError:
            return "File not found!"
        
        for row in result:
            c.PROBLEM_NAMES[row['text']] = [row[f"canonical_form_{x}"] for x in range(1, 4)
                                            if row[f"canonical_form_{x}"]]

    
    @property
    def CHERRYPY(self):
        return _config['cherrypy']
    
    @property
    def RECEIPT_CATEGORY_OPTS(self):
        opts = []
        for key, dict in c.RECEIPT_DEPT_CATEGORIES.items():
            opts.extend([(key, val) for key, val in dict.items()])
        return opts

    @property
    def DEALER_REG_OPEN(self):
        return self.AFTER_DEALER_REG_START and self.BEFORE_DEALER_REG_SHUTDOWN

    @property
    @dynamic
    def DEALER_REG_SOFT_CLOSED(self):
        return self.AFTER_DEALER_REG_DEADLINE or self.DEALER_APPS >= self.MAX_DEALER_APPS \
            if self.MAX_DEALER_APPS else self.AFTER_DEALER_REG_DEADLINE
    
    @property
    def DEALER_INDEFINITE_TERM(self):
        if c.DEALER_TERM.startswith(("a", "e", "i", "o", "u")):
            return "an " + c.DEALER_TERM
        else:
            return "a " + c.DEALER_TERM

    @property
    def TABLE_OPTS(self):
        return [(x, str(x)) for x in list(range(1, c.MAX_TABLES + 1))]

    @property
    def ADMIN_TABLE_OPTS(self):
        return [(0, '0')] + c.TABLE_OPTS

    @property
    def PREREG_TABLE_OPTS(self):
        return [(count, '{}: ${}'.format(desc, self.get_table_price(count)))
                for count, desc in c.TABLE_OPTS]

    @property
    def ART_SHOW_OPEN(self):
        return self.AFTER_ART_SHOW_REG_START and self.BEFORE_ART_SHOW_DEADLINE
    
    @property
    def ART_SHOW_HAS_FEES(self):
        return c.COST_PER_PANEL or c.COST_PER_TABLE or c.ART_MAILING_FEE
    
    @property
    def MARKETPLACE_CANCEL_DEADLINE(self):
        return min(self.EPOCH, self.PREREG_TAKEDOWN) if self.PREREG_TAKEDOWN else self.EPOCH

    @property
    def SELF_SERVICE_REFUNDS_OPEN(self):
        return self.BEFORE_REFUND_CUTOFF and (self.AFTER_REFUND_START or not self.REFUND_START)
    
    @property
    def HOTEL_LOTTERY_OPEN(self):
        return c.AFTER_HOTEL_LOTTERY_FORM_START and c.BEFORE_HOTEL_LOTTERY_FORM_DEADLINE
    
    @property
    def STAFF_HOTEL_LOTTERY_OPEN(self):
        return c.AFTER_HOTEL_LOTTERY_STAFF_START and c.BEFORE_HOTEL_LOTTERY_STAFF_DEADLINE

    @property
    def SHOW_HOTEL_LOTTERY_DATE_OPTS(self):
        return c.HOTEL_LOTTERY_CHECKIN_START != c.HOTEL_LOTTERY_CHECKIN_END

    @property
    def HOTEL_LOTTERY_FORM_STEPS(self):
        """
        We have to run our form validations based on which 'step' in the form someone is, but
        the number of steps depends on the entry type and event config. This builds
        a dict that allows you to look up each step number based on a key.
        """

        steps = {}
        step = 0
        if c.SHOW_HOTEL_LOTTERY_DATE_OPTS:
            step += 1
            steps['room_dates'] = step
        step += 1
        steps['room_ada_info'] = step
        step += 1
        steps['room_hotel_type'] = step
        if c.HOTEL_LOTTERY_PREF_RANKING:
            step += 1
            steps['room_selection_pref'] = step
        steps['room_final_step'] = step

        step = 1
        steps['suite_agreement'] = step
        if c.SHOW_HOTEL_LOTTERY_DATE_OPTS:
            step += 1
            steps['suite_dates'] = step
        step += 1
        steps['suite_type'] = step
        step += 1
        steps['suite_hotel_type'] = step
        if c.HOTEL_LOTTERY_PREF_RANKING:
            step += 1
            steps['suite_selection_pref'] = step
        steps['suite_final_step'] = step

        return steps

    @request_cached_property
    @dynamic
    def DEALER_APPS(self):
        from uber.models import Session, Group
        with Session() as session:
            return session.query(Group).filter(
                Group.tables > 0,
                Group.cost > 0,
                Group.status == self.UNAPPROVED).count()

    @request_cached_property
    @dynamic
    def ATTENDEE_BADGE_COUNT(self):
        """
        Adds paid promo codes to the badge count, since these are promised badges and this property is used for our
        badge sales cap. Free PC groups are excluded as they often have far more badges than will ever be claimed.
        """
        from uber.models import Session, PromoCode, PromoCodeGroup
        base_count = self.get_badge_count_by_type(c.ATTENDEE_BADGE)
        with Session() as session:
            pc_code_count = session.query(PromoCode).join(PromoCodeGroup).filter(PromoCode.cost > 0,
                                                                                 PromoCode.uses_remaining > 0).count()
        return base_count + pc_code_count

    @request_cached_property
    @dynamic
    def BADGES_SOLD(self):
        """
        The number of badges that we've sold, including all badge types and promo code groups' badges.
        This is used for bucket-based pricing and to estimate year-over-year sales.
        """
        from uber.models import Session, Attendee, Group, PromoCode, PromoCodeGroup
        if self.BADGES_SOLD_ESTIMATE_ENABLED:
            with Session() as session:
                attendee_count = int(session.execute(
                    "SELECT reltuples AS count FROM pg_class WHERE relname = 'attendee'").scalar())

                # This will be efficient because we've indexed attendee(badge_type, badge_status)
                staff_count = self.get_badge_count_by_type(c.STAFF_BADGE)
                return max(0, attendee_count - staff_count)
        else:
            with Session() as session:
                attendees = session.query(Attendee)
                individuals = attendees.filter(Attendee.has_badge == True, or_(  # noqa: E712
                    Attendee.paid == self.HAS_PAID,
                    Attendee.paid == self.REFUNDED)
                ).filter(Attendee.badge_status == self.COMPLETED_STATUS).count()

                group_badges = attendees.join(Attendee.group).filter(
                    Attendee.has_badge == True,  # noqa: E712
                    Attendee.paid == self.PAID_BY_GROUP,
                    Group.amount_paid > 0).count()

                promo_code_badges = session.query(PromoCode).join(PromoCodeGroup).filter(PromoCode.cost > 0).count()

                return individuals + group_badges + promo_code_badges

    @request_cached_property
    @dynamic
    def BADGES_LEFT_AT_CURRENT_PRICE(self):
        """
        Returns a string representing a rough estimate of how many badges are left at the current badge price tier.
        """
        is_badge_price_ordered = c.BADGE_PRICE in c.ORDERED_PRICE_LIMITS
        current_price_tier = c.ORDERED_PRICE_LIMITS.index(c.BADGE_PRICE) if is_badge_price_ordered else -1

        if current_price_tier != -1 and c.ORDERED_PRICE_LIMITS[current_price_tier] == c.ORDERED_PRICE_LIMITS[-1] \
                or not c.ORDERED_PRICE_LIMITS:
            return -1
        else:
            for key, val in c.PRICE_LIMITS.items():
                if c.ORDERED_PRICE_LIMITS[current_price_tier+1] == val:
                    difference = key - c.BADGES_SOLD
        return difference

    @property
    @dynamic
    def ONEDAY_BADGE_PRICE(self):
        return self.get_oneday_price(uber.utils.localized_now())

    @property
    @dynamic
    def BADGE_PRICE(self):
        return self.get_attendee_price()

    @property
    @dynamic
    def GROUP_PRICE(self):
        return self.get_group_price()

    @property
    def PREREG_BADGE_TYPES(self):
        types = [self.ATTENDEE_BADGE, self.PSEUDO_DEALER_BADGE]
        if c.UNDER_13 in c.AGE_GROUP_CONFIGS and c.AGE_GROUP_CONFIGS[c.UNDER_13]['can_register']:
            types.append(self.CHILD_BADGE)
        for reg_open, badge_type in [(self.BEFORE_GROUP_PREREG_TAKEDOWN, self.PSEUDO_GROUP_BADGE)]:
            if reg_open:
                types.append(badge_type)
        for badge_type in self.BADGE_TYPE_PRICES:
            if badge_type not in types:
                types.append(badge_type)
        return types

    @property
    @dynamic
    def PRESOLD_ONEDAY_BADGE_TYPES(self):
        return {
            badge_type: self.BADGES[badge_type]
            for badge_type, desc in self.AT_THE_DOOR_BADGE_OPTS
            if self.BADGES[badge_type] in c.DAYS_OF_WEEK
        }

    @property
    def FORMATTED_BADGE_TYPES(self):
        badge_types = []
        if c.AT_THE_CON and self.ONE_DAYS_ENABLED and self.ONE_DAY_BADGE_AVAILABLE:
            badge_types.append({
                'name': 'Single Day',
                'desc': 'Can be upgraded to a weekend badge later.',
                'value': c.ONE_DAY_BADGE,
                'price': c.ONEDAY_BADGE_PRICE
            })
        badge_types.append({
            'name': 'Attendee',
            'desc': 'Allows access to the convention for its duration.',
            'value': c.ATTENDEE_BADGE,
            'price': c.get_attendee_price()
            })
        for badge_type in c.BADGE_TYPE_PRICES:
            badge_types.append({
                'name': c.BADGES[badge_type],
                'desc': 'Donate extra to get an upgraded badge with perks.',
                'value': badge_type,
                'price': c.BADGE_TYPE_PRICES[badge_type]
            })
        return badge_types

    @request_cached_property
    @dynamic
    def SOLD_OUT_BADGE_TYPES(self):
        # Override in event plugin based on your specific badge types
        return []

    @property
    def kickin_availability_matrix(self):
        return dict([[
            getattr(self, level + "_LEVEL"), getattr(self, level + "_AVAILABLE")]
            for level in ['SHIRT', 'SUPPORTER', 'SEASON']
        ])

    @property
    def PREREG_DONATION_OPTS(self):
        # TODO: Remove this once the admin form is converted to the new form system

        if not self.SHARED_KICKIN_STOCKS:
            return [(amt, desc) for amt, desc in self.DONATION_TIER_OPTS
                    if amt not in self.kickin_availability_matrix or self.kickin_availability_matrix[amt]]

        if self.BEFORE_SHIRT_DEADLINE and not self.SHIRT_AVAILABLE:
            return [(amt, desc) for amt, desc in self.DONATION_TIER_OPTS if amt < self.SHIRT_LEVEL]
        elif self.BEFORE_SUPPORTER_DEADLINE and not self.SUPPORTER_AVAILABLE:
            return [(amt, desc) for amt, desc in self.DONATION_TIER_OPTS if amt < self.SUPPORTER_LEVEL]
        elif self.BEFORE_SUPPORTER_DEADLINE and not self.SEASON_AVAILABLE:
            return [(amt, desc) for amt, desc in self.DONATION_TIER_OPTS if amt < self.SEASON_LEVEL]
        else:
            return self.DONATION_TIER_OPTS

    @property
    def FORMATTED_DONATION_DESCRIPTIONS(self):
        # TODO: Remove this once the admin form is converted to the new form system

        """
        A list of the donation descriptions, formatted for use on attendee-facing pages.

        This does NOT filter out unavailable kick-ins so we can use it on attendees' confirmation pages
        to show unavailable kick-ins they've already purchased. To show only available kick-ins, use
        PREREG_DONATION_DESCRIPTIONS.
        """
        donation_list = self.DONATION_TIER_DESCRIPTIONS.items()

        donation_list = sorted(donation_list, key=lambda tier: tier[1]['price'])

        # add in all previous descriptions.  the higher tiers include all the lower tiers
        for entry in donation_list:
            all_desc_and_links = \
                [(tier[1]['description'], tier[1]['link']) for tier in donation_list
                    if tier[1]['price'] > 0 and tier[1]['price'] < entry[1]['price']] \
                + [(entry[1]['description'], entry[1]['link'])]

            # maybe slight hack. descriptions and links are separated by '|' characters so we can have multiple
            # items displayed in the donation tiers.  in an ideal world, these would already be separated in the INI
            # and we wouldn't have to do it here.
            entry[1]['all_descriptions'] = []
            for item in all_desc_and_links:
                descriptions = item[0].split('|')
                links = item[1].split('|')
                entry[1]['all_descriptions'] += list(zip(descriptions, links))

        return [dict(tier[1]) for tier in donation_list]

    @property
    def UNAVAILABLE_REG_TYPES(self):
        unavailable_types = []

        if c.GROUPS_ENABLED and c.AFTER_GROUP_PREREG_TAKEDOWN:
            unavailable_types.append(c.PSEUDO_GROUP_BADGE)

        if c.CHILD_BADGE in c.PREREG_BADGE_TYPES and not c.CHILD_BADGE_AVAILABLE:
            unavailable_types.append(c.CHILD_BADGE)

        return unavailable_types

    @property
    def FORMATTED_REG_TYPES(self):
        # Returns a formatted list to help attendees select between different types of registrations,
        # particularly between individual reg, group reg, and a child badge. Note that all values should
        # correspond to a badge type and will change the hidden badge type input on the prereg page.

        reg_type_opts = [{
            'name': "Attendee",
            'desc': "A single registration; you can register more before paying.",
            'value': c.ATTENDEE_BADGE,
            'price': c.BADGE_PRICE,
            }]

        if c.GROUPS_ENABLED and (c.BEFORE_GROUP_PREREG_TAKEDOWN or not c.AT_THE_CON):
            reg_type_opts.append({
                'name': "Group Leader",
                'desc': Markup(f"Register a group of {c.MIN_GROUP_SIZE} people or more at ${c.GROUP_PRICE} per badge."
                               "<br/><br/><span class='form-text'>Please purchase badges for children 12 and under "
                               "separate from your group.</span>"),
                'value': c.PSEUDO_GROUP_BADGE,
                'price': c.GROUP_PRICE,
            })

        if c.CHILD_BADGE in c.PREREG_BADGE_TYPES:
            reg_type_opts.append({
                'name': "12 and Under",
                'desc': Markup(f"Attendees 12 and younger at the start of {c.EVENT_NAME} must be accompanied "
                               "by an adult with a valid Attendee badge. <br/><br/>"
                               "<span class='form-text text-danger'>Price is always half that of the Single "
                               "Attendee badge price. Badges for attendees 5 and younger are free.</span>"),
                'value': c.CHILD_BADGE,
                'price': str(c.BADGE_PRICE - math.ceil(c.BADGE_PRICE / 2)),
            })

        return reg_type_opts

    @property
    def SOLD_OUT_MERCH_TIERS(self):
        if not self.SHARED_KICKIN_STOCKS:
            return [price for price, available in self.kickin_availability_matrix.items() if available is False]

        if self.BEFORE_SHIRT_DEADLINE and not self.SHIRT_AVAILABLE:
            return [price for price, name in self.DONATION_TIERS.items() if price >= self.SHIRT_LEVEL]
        elif self.BEFORE_SUPPORTER_DEADLINE and not self.SUPPORTER_AVAILABLE:
            return [price for price, name in self.DONATION_TIERS.items() if price >= self.SUPPORTER_LEVEL]
        elif self.BEFORE_SUPPORTER_DEADLINE and not self.SEASON_AVAILABLE:
            return [price for price, name in self.DONATION_TIERS.items() if price >= self.SEASON_LEVEL]

        return []

    @property
    def AVAILABLE_MERCH_TIERS(self):
        return sorted([price for price, name in self.DONATION_TIERS.items() if price not in self.SOLD_OUT_MERCH_TIERS])

    @property
    def FORMATTED_MERCH_TIERS(self):
        # Formats the data from DONATION_TIER_DESCRIPTIONS to match what the 'card_select' form macro expects.

        donation_list = self.DONATION_TIER_DESCRIPTIONS.items()

        donation_list = sorted(donation_list, key=lambda tier: tier[1]['price'])

        merch_tiers = []

        for entry in donation_list:
            tier = entry[1].copy()
            if '|' in tier['description']:
                item_list = tier['description'].split('|')
                formatted_desc = item_list[0]
                for item in item_list[1:]:
                    formatted_desc += "<hr class='m-2'>" + item
                tier['desc'] = Markup(formatted_desc)
            else:
                tier['desc'] = tier['description']

            tier.pop('description', '')
            tier.pop('merch_items', '')

            merch_tiers.append(tier)

        return merch_tiers

    @property
    def PREREG_DONATION_DESCRIPTIONS(self):
        # TODO: Remove this once the admin form is converted to the new form system

        donation_list = self.FORMATTED_DONATION_DESCRIPTIONS

        # include only the items that are actually available for purchase
        if not self.SHARED_KICKIN_STOCKS:
            donation_list = [tier for tier in donation_list
                             if tier['price'] not in self.kickin_availability_matrix
                             or self.kickin_availability_matrix[tier['price']]]
        elif self.BEFORE_SHIRT_DEADLINE and not self.SHIRT_AVAILABLE:
            donation_list = [tier for tier in donation_list if tier['price'] < self.SHIRT_LEVEL]
        elif self.BEFORE_SUPPORTER_DEADLINE and not self.SUPPORTER_AVAILABLE:
            donation_list = [tier for tier in donation_list if tier['price'] < self.SUPPORTER_LEVEL]
        elif self.BEFORE_SUPPORTER_DEADLINE and not self.SEASON_AVAILABLE:
            donation_list = [tier for tier in donation_list if tier['price'] < self.SEASON_LEVEL]

        return [tier for tier in donation_list if
                (tier['price'] >= c.SHIRT_LEVEL and tier['price'] < c.SUPPORTER_LEVEL and c.BEFORE_SHIRT_DEADLINE) or
                (tier['price'] >= c.SUPPORTER_LEVEL and c.BEFORE_SUPPORTER_DEADLINE) or
                tier['price'] < c.SHIRT_LEVEL]

    @property
    def FORMATTED_DONATION_DESCRIPTIONS_EXCLUSIVE(self):
        """
        A list of the donation descriptions, formatted for use on attendee-facing pages.
        """
        donation_list = self.DONATION_TIER_DESCRIPTIONS.items()

        donation_list = sorted(donation_list, key=lambda tier: tier[1]['value'])

        # add in all previous descriptions.  the higher tiers include all the lower tiers
        for entry in donation_list:
            all_desc_and_links = \
                [(tier[1]['description'], tier[1]['link']) for tier in donation_list
                    if tier[1]['value'] > 0 and tier[1]['value'] < entry[1]['value']] \
                + [(entry[1]['description'], entry[1]['link'])]

            # maybe slight hack. descriptions and links are separated by '|' characters so we can have multiple
            # items displayed in the donation tiers.  in an ideal world, these would already be separated in the INI
            # and we wouldn't have to do it here.
            entry[1]['all_descriptions'] = []
            for item in all_desc_and_links:
                descriptions = item[0].split('|')
                links = item[1].split('|')
                entry[1]['all_descriptions'] += list(zip(descriptions, links))

        return [dict(tier[1]) for tier in donation_list]

    @property
    def PREREG_DONATION_DESCRIPTIONS_EXCLUSIVE(self):
        donation_list = self.FORMATTED_DONATION_DESCRIPTIONS_EXCLUSIVE

        # include only the items that are actually available for purchase
        if not self.SHARED_KICKIN_STOCKS:
            donation_list = [tier for tier in donation_list
                             if tier['value'] not in self.kickin_availability_matrix
                             or self.kickin_availability_matrix[tier['value']]]
        elif self.BEFORE_SHIRT_DEADLINE and not self.SHIRT_AVAILABLE:
            donation_list = [tier for tier in donation_list if tier['value'] < self.SHIRT_LEVEL]
        elif self.BEFORE_SUPPORTER_DEADLINE and not self.SUPPORTER_AVAILABLE:
            donation_list = [tier for tier in donation_list if tier['value'] < self.SUPPORTER_LEVEL]
        elif self.BEFORE_SUPPORTER_DEADLINE and self.SEASON_AVAILABLE:
            donation_list = [tier for tier in donation_list if tier['value'] < self.SEASON_LEVEL]

        return [tier for tier in donation_list if
                (tier['value'] >= c.SHIRT_LEVEL and tier['value'] < c.SUPPORTER_LEVEL and c.BEFORE_SHIRT_DEADLINE) or
                (tier['value'] >= c.SUPPORTER_LEVEL and c.BEFORE_SUPPORTER_DEADLINE) or
                tier['value'] < c.SHIRT_LEVEL]

    @property
    def PREREG_DONATION_TIERS(self):
        return dict(self.PREREG_DONATION_OPTS)

    @property
    def ONE_WEEK_OR_TAKEDOWN_OR_EPOCH(self):
        week_from_now = c.EVENT_TIMEZONE.localize(datetime.combine(date.today() + timedelta(days=7), time(23, 59)))
        return min(week_from_now, c.UBER_TAKEDOWN, c.EPOCH)

    @request_cached_property
    @dynamic
    def AT_THE_DOOR_BADGE_OPTS(self):
        """
        This provides the dropdown on the /registration/register page with its
        list of badges available at-door.  It includes a "Full Weekend Badge"
        if attendee badges are available.  If one-days are enabled, it includes
        either a generic "Single Day Badge" or a list of specific day badges,
        based on the c.PRESELL_ONE_DAYS setting.
        """
        opts = []
        if self.ATTENDEE_BADGE_AVAILABLE:
            opts.append((self.ATTENDEE_BADGE, 'Full Weekend Badge (${})'.format(self.BADGE_PRICE)))
        for badge_type in self.BADGE_TYPE_PRICES:
            if badge_type not in opts:
                opts.append(
                    (badge_type, '{} (${})'.format(self.BADGES[badge_type], self.BADGE_TYPE_PRICES[badge_type])))
            opts.append((self.ATTENDEE_BADGE, 'Standard (${})'.format(self.BADGE_PRICE)))
        if self.ONE_DAYS_ENABLED:
            if self.PRESELL_ONE_DAYS:
                day = max(uber.utils.localized_now(), self.EPOCH)
                while day.date() <= self.ESCHATON.date():
                    day_name = day.strftime('%A')
                    price = self.BADGE_PRICES['single_day'].get(day_name) or self.DEFAULT_SINGLE_DAY
                    badge = getattr(self, day_name.upper())
                    if getattr(self, day_name.upper() + '_AVAILABLE', None):
                        opts.append((badge, day_name + ' Badge (${})'.format(price)))
                    day += timedelta(days=1)
            elif self.ONE_DAY_BADGE_AVAILABLE:
                opts.append((self.ONE_DAY_BADGE, 'Single Day Badge (${})'.format(self.ONEDAY_BADGE_PRICE)))
        return opts

    @property
    def PREREG_AGE_GROUP_OPTS(self):
        return [opt for opt in self.AGE_GROUP_OPTS if opt[0] != self.AGE_UNKNOWN]

    @property
    def NOW_OR_AT_CON(self):
        return c.EPOCH.date() if date.today() <= c.EPOCH.date() else uber.utils.localized_now().date()

    @property
    def AT_OR_POST_CON(self):
        return self.AT_THE_CON or self.POST_CON

    @property
    def PRE_CON(self):
        return not self.AT_OR_POST_CON

    @property
    def FINAL_EMAIL_DEADLINE(self):
        return min(c.UBER_TAKEDOWN, c.EPOCH)

    @property
    def CSRF_TOKEN(self):
        uber.utils.ensure_csrf_token_exists()
        return cherrypy.session.get('csrf_token', '')

    @property
    def QUERY_STRING(self):
        return cherrypy.request.query_string

    @property
    def QUERY_STRING_NO_MSG(self):
        from urllib.parse import parse_qsl, urlencode

        query = parse_qsl(cherrypy.request.query_string, keep_blank_values=True)
        query = [(key, val) for (key, val) in query if key != 'message']
        return urlencode(query)

    @property
    def PAGE_PATH(self):
        return cherrypy.request.path_info

    @property
    def PAGE(self):
        return cherrypy.request.path_info.split('/')[-1]
    
    @property
    def INDEXABLE_PAGE_PATHS(self):
        """
        Even if we ban crawlers via robots.txt, if anyone publishes a link to a protected
        page it will end up on Bing, private UUID and all. Instead we want to ban indexing
        via the meta tag for everything except these pages.
        """
        index_pages = ['/landing/', '/landing/index', '/pregistration/form', '/accounts/login']
        if c.SHIFTS_CREATED:
            index_pages.append('/staffing/login')
        if c.TRANSFERABLE_BADGE_TYPES:
            index_pages.append('/preregistration/start_badge_transfer')
        if not c.ATTENDEE_ACCOUNTS_ENABLED:
            index_pages.append('/preregistration/check_if_preregistered')
        return index_pages

    @request_cached_property
    @dynamic
    def ALLOWED_ACCESS_OPTS(self):
        with uber.models.Session() as session:
            return session.current_admin_account().allowed_access_opts

    @request_cached_property
    @dynamic
    def DISALLOWED_ACCESS_OPTS(self):
        return set(self.ACCESS_OPTS).difference(set(self.ALLOWED_ACCESS_OPTS))

    @request_cached_property
    @dynamic
    def CURRENT_ADMIN(self):
        try:
            from uber.models import Session, AdminAccount, Attendee
            with Session() as session:
                attrs = Attendee.to_dict_default_attrs + ['admin_account', 'assigned_depts', 'logged_in_name']
                admin_account = session.query(AdminAccount) \
                    .filter_by(id=cherrypy.session.get('account_id')) \
                    .options(subqueryload(AdminAccount.attendee).subqueryload(Attendee.assigned_depts)).one()

                return admin_account.attendee.to_dict(attrs)
        except Exception:
            return {}

    @request_cached_property
    @dynamic
    def CURRENT_VOLUNTEER(self):
        try:
            from uber.models import Session, Attendee
            with Session() as session:
                attrs = Attendee.to_dict_default_attrs + ['logged_in_name']
                attendee = session.logged_in_volunteer()
                return attendee.to_dict(attrs)
        except Exception:
            return {}
        
    @request_cached_property
    @dynamic
    def CURRENT_KIOSK_SUPERVISOR(self):
        try:
            from uber.models import Session
            with Session() as session:
                admin_account = session.current_supervisor_admin()
                return admin_account.attendee.to_dict()
        except Exception:
            return {}
    
    @request_cached_property
    @dynamic
    def CURRENT_KIOSK_OPERATOR(self):
        try:
            from uber.models import Session
            with Session() as session:
                attendee = session.kiosk_operator_attendee()
                return attendee.to_dict()
        except Exception:
            return {}

    @request_cached_property
    @dynamic
    def DEPARTMENTS(self):
        return dict(self.DEPARTMENT_OPTS)

    @request_cached_property
    @dynamic
    def DEPARTMENT_OPTS(self):
        from uber.models import Session, Department
        with Session() as session:
            query = session.query(Department).order_by(Department.name)
            return [(d.id, d.name) for d in query]

    @request_cached_property
    @dynamic
    def DEPARTMENT_OPTS_WITH_DESC(self):
        from uber.models import Session, Department
        with Session() as session:
            query = session.query(Department).order_by(Department.name)
            return [(d.id, d.name, d.description) for d in query]

    @request_cached_property
    @dynamic
    def PUBLIC_DEPARTMENT_OPTS_WITH_DESC(self):
        from uber.models import Session, Department
        with Session() as session:
            query = session.query(Department).filter_by(
                solicits_volunteers=True).order_by(Department.name)
            return [('All', 'Anywhere', 'I want to help anywhere I can!')] \
                + [(d.id, d.name, d.description) for d in query]

    @request_cached_property
    @dynamic
    def ADMIN_DEPARTMENTS(self):
        return dict(self.ADMIN_DEPARTMENT_OPTS)

    @request_cached_property
    @dynamic
    def ADMIN_DEPARTMENT_OPTS(self):
        from uber.models import Session, Department

        with Session() as session:
            query = session.query(Department).order_by(Department.name)
            if not query.first():
                return [(-1, -1)]
            current_admin = session.current_admin_account()
            if current_admin.full_shifts_admin:
                return [(d.id, d.name) for d in query]
            else:
                return [(d.id, d.name) for d in query if d.id in
                        [str(d.id) for d in current_admin.attendee.dept_memberships_with_inherent_role]]

    @request_cached_property
    @dynamic
    def DEFAULT_DEPARTMENT_ID(self):
        return list(c.ADMIN_DEPARTMENTS.keys())[0] if c.ADMIN_DEPARTMENTS else 0

    @property
    def HTTP_METHOD(self):
        return cherrypy.request.method.upper()

    def get_kickin_count(self, kickin_level):
        from uber.models import Session, Attendee
        with Session() as session:
            count = session.query(Attendee).filter_by(amount_extra=kickin_level).filter(
                    ~Attendee.badge_status.in_([c.INVALID_GROUP_STATUS, c.INVALID_STATUS,
                                                c.IMPORTED_STATUS, c.REFUNDED_STATUS])).count()
        return count

    def get_shirt_count(self, shirt_enum_key):
        from uber.models import Session, Attendee
        with Session() as session:
            shirt_count = 0

            base_filters = [Attendee.shirt == shirt_enum_key,
                            ~Attendee.badge_status.in_([c.INVALID_GROUP_STATUS, c.INVALID_STATUS,
                                                        c.IMPORTED_STATUS, c.REFUNDED_STATUS])]
            base_query = session.query(Attendee).filter(*base_filters)

            # Paid event shirts
            shirt_count += base_query.filter(Attendee.amount_extra >= c.SHIRT_LEVEL).count()

            if c.SHIRTS_PER_STAFFER > 0:
                staff_event_shirts = session.query(func.sum(Attendee.num_event_shirts)).filter(*base_filters).filter(
                    Attendee.badge_type == c.STAFF_BADGE, Attendee.num_event_shirts != -1).scalar()
                shirt_count += staff_event_shirts or 0

            if c.HOURS_FOR_SHIRT:
                shirt_count += base_query.filter(Attendee.ribbon.contains(c.VOLUNTEER_RIBBON)).count()

        return shirt_count

    @property
    def STAFF_SHIRT_FIELD_ENABLED(self):
        return c.SHIRTS_PER_STAFFER > 0 and c.SHIRT_OPTS != c.STAFF_SHIRT_OPTS

    @property
    def STAFF_GET_EVENT_SHIRTS(self):
        return (c.SHIRTS_PER_STAFFER > 0 and c.STAFF_EVENT_SHIRT_OPTS) or (c.SHIRTS_PER_STAFFER == 0 and c.HOURS_FOR_SHIRT)

    @request_cached_property
    @dynamic
    def SEASON_COUNT(self):
        return self.get_kickin_count(self.SEASON_LEVEL)

    @request_cached_property
    @dynamic
    def SUPPORTER_COUNT(self):
        return self.get_kickin_count(self.SUPPORTER_LEVEL)

    @request_cached_property
    @dynamic
    def SHIRT_COUNT(self):
        return self.get_kickin_count(self.SHIRT_LEVEL)

    @property
    @dynamic
    def REMAINING_BADGES(self):
        return max(0, self.ATTENDEE_BADGE_STOCK - self.ATTENDEE_BADGE_COUNT)

    @request_cached_property
    @dynamic
    def MENU_FILTERED_BY_ACCESS_LEVELS(self):
        return c.MENU.render_items_filtered_by_current_access()

    @request_cached_property
    @dynamic
    def ACCESS_GROUPS(self):
        return dict(self.ACCESS_GROUP_OPTS)

    @request_cached_property
    @dynamic
    def ACCESS_GROUP_OPTS(self):
        from uber.models import Session, AccessGroup
        with Session() as session:
            query = session.query(AccessGroup).order_by(AccessGroup.name)
            return [(a.id, a.name) for a in query]

    @request_cached_property
    @dynamic
    def ADMIN_ACCESS_SET(self):
        return uber.models.AdminAccount.get_access_set(include_read_only=True)

    @request_cached_property
    @dynamic
    def ADMIN_WRITE_ACCESS_SET(self):
        return uber.models.AdminAccount.get_access_set()

    @cached_property
    def ADMIN_PAGES(self):
        public_site_sections, public_pages, pages = self.GETTABLE_SITE_PAGES
        site_sections = cherrypy.tree.apps[c.CHERRYPY_MOUNT_PATH].root

        return {
            section: [opt for opt in dir(getattr(site_sections, section))
                      if opt not in public_pages and not opt.startswith('_')]
            for section in dir(site_sections) if section not in public_site_sections and not section.startswith('_')
        }

    @request_cached_property
    def SITE_MAP(self):
        public_site_sections, public_pages, pages = self.GETTABLE_SITE_PAGES

        accessible_site_sections = defaultdict(list)
        for section in pages:
            accessible_pages = [page for page in pages[section]
                                if c.has_section_or_page_access(page_path=page['path'], include_read_only=True)]
            if accessible_pages:
                accessible_site_sections[section] = accessible_pages

        return sorted(accessible_site_sections.items())

    @cached_property
    def GETTABLE_SITE_PAGES(self):
        """
        Introspects all available pages in the application and returns several data structures for use
        in displaying them.
        Returns:
            public_site_sections (list): a list of site sections that are accessible to the public, e.g.,
                'preregistration'
            public_pages (list): a list of individual pages in non-public site sections that are accessible to the
                public, prepended by their site section; e.g., 'registration_register' for registration/register
            pages (defaultdict(list)): a dictionary with keys corresponding to site sections, each key containing
                a list of key/value pairs for each page inside that section.
                Example:
                    pages['registration'] = [
                        {'name': 'Arbitrary Charge Form', 'path': '/merch_admin/arbitrary_charge_form'},
                        {'name': 'Comments', 'path': '/registration/comments'},
                        {'name': 'Discount', 'path': '/registration/discount'},
                    ]
        """
        public_site_sections = ['static_views', 'public', 'staffing']
        public_pages = []
        site_sections = cherrypy.tree.apps[c.CHERRYPY_MOUNT_PATH].root
        modules = {name: getattr(site_sections, name) for name in dir(site_sections) if not name.startswith('_')}
        pages = defaultdict(list)
        for module_name, module_root in modules.items():
            page_method = getattr(site_sections, module_name)
            if getattr(page_method, 'public', False):
                public_site_sections.append(module_name)
            for name in dir(module_root):
                method = getattr(module_root, name)
                if getattr(page_method, 'public', False):
                    public_pages.append(module_name + "_" + name)
                if getattr(method, 'exposed', False):
                    spec = inspect.getfullargspec(unwrap(method))
                    has_defaults = len([arg for arg in spec.args[1:] if arg != 'session']) == len(spec.defaults or [])
                    if not getattr(method, 'ajax', False) and (getattr(method, 'site_mappable', False)
                                                               or has_defaults and not spec.varkw) \
                            and not getattr(method, 'not_site_mappable', False):
                        pages[module_name].append({
                            'name': name.replace('_', ' ').title(),
                            'path': '/{}/{}'.format(module_name, name),
                            'is_download': getattr(method, 'site_map_download', False)
                        })
        return public_site_sections, public_pages, pages
    
    def get_signature_by_sender(self, sender):
        from uber.custom_tags import email_only

        config_opt = email_only(sender).split('@')[0]
        signature_key = getattr(self, config_opt, None)
        if signature_key:
            return self.EMAIL_SIGNATURES[signature_key]
        return ""

    # =========================
    # mivs
    # =========================

    @property
    @dynamic
    def CAN_SUBMIT_MIVS(self):
        return self.MIVS_SUBMISSIONS_OPEN or self.HAS_MIVS_ADMIN_ACCESS

    @property
    @dynamic
    def MIVS_SUBMISSIONS_OPEN(self):
        return not really_past_mivs_deadline(c.MIVS_DEADLINE) and self.AFTER_MIVS_START

    # =========================
    # panels
    # =========================

    @request_cached_property
    @dynamic
    def PANEL_POC_OPTS(self):
        from uber.models import Session, AdminAccount
        with Session() as session:
            return sorted([
                (a.attendee.id, a.attendee.full_name)
                for a in session.query(AdminAccount).options(joinedload(AdminAccount.attendee))
                if 'panels_admin' in a.read_or_write_access_set
            ], key=lambda tup: tup[1], reverse=False)
        
    @request_cached_property
    @dynamic
    def get_panels_id(self):
        from uber.models import Session, Department

        with Session() as session:
            panels_dept = session.query(Department).filter(Department.manages_panels == True, 
                                                           Department.name == "Panels").first()
            if panels_dept:
                return panels_dept.id
            else:
                return c.PANELS

    @request_cached_property
    @dynamic
    def PANELS_DEPT_OPTS_WITH_DESC(self):
        from uber.models import Session, Department
        opt_list = []

        with Session() as session:
            panel_depts = session.query(Department).filter(Department.manages_panels == True)
            panels = panel_depts.filter(Department.name == "Panels").first()

            if panels:
                opt_list.append((panels.id, panels.name, panels.panels_desc))
            else:
                opt_list.append((str(c.PANELS), "Panels", ''))
            
            if not panel_depts.count():
                return opt_list

            for dept in panel_depts:
                if dept.name != "Panels":
                    opt_list.append((dept.id, dept.name, dept.panels_desc))

        return opt_list
    
    @request_cached_property
    @dynamic
    def PANELS_DEPT_OPTS(self):
        return [(key, name) for key, name, _ in self.PANELS_DEPT_OPTS_WITH_DESC]
    
    @request_cached_property
    @dynamic
    def EMAILLESS_PANEL_DEPTS(self):
        from uber.models import Session, Department

        id_list = [c.PANELS]
        with Session() as session:
            panels_depts_query = session.query(Department).filter(Department.manages_panels == True)
            for dept in panels_depts_query.filter(or_(Department.from_email == '',
                                                      Department.from_email == c.PANELS_EMAIL)):
                id_list.append(dept.id)
        return id_list

    def __getattr__(self, name):
        if name.split('_')[0] in ['BEFORE', 'AFTER']:
            date_setting = getattr(c, name.split('_', 1)[1])
            if not date_setting:
                return False
            elif name.startswith('BEFORE_'):
                return uber.utils.localized_now() < date_setting
            else:
                return uber.utils.localized_now() > date_setting
        elif name.startswith('HAS_') and name.endswith('_ACCESS'):
            access_name = '_'.join(name.split('_')[1:-1]).lower()

            # No page specified means current page or section
            if access_name == '':
                return self.has_section_or_page_access()
            elif access_name == 'read':
                return self.has_section_or_page_access(include_read_only=True)

            if access_name.endswith('_read'):
                return access_name[:-5] in self.ADMIN_ACCESS_SET
            return access_name in self.ADMIN_WRITE_ACCESS_SET
        elif name.endswith('_COUNT'):
            item_check = name.rsplit('_', 1)[0]
            badge_type = getattr(self, item_check, None)
            return self.get_badge_count_by_type(badge_type) if badge_type else None
        elif name.endswith('_AVAILABLE'):
            item_check = name.rsplit('_', 1)[0]
            stock_setting = getattr(self, item_check + '_STOCK', None)
            if stock_setting is None:
                # Defaults to unlimited stock for any stock not configured
                return True

            # Only poll the DB if stock is configured
            count_check = getattr(self, item_check + '_COUNT', None)
            if count_check is None:
                # Things with no count are never considered available
                return False
            else:
                return int(count_check) < int(stock_setting)
        elif name.lower() in _config['secret']:
            return _config['secret'][name.lower()]
        else:
            raise AttributeError('no such attribute {}'.format(name))


class AWSSecretFetcher:
    """
    This class manages fetching secrets from AWS. Some secrets only need to be
    fetched once, while others may be re-fetched to refresh tokens.
    """

    def __init__(self):
        self.start_session()

    def start_session(self):
        import boto3

        aws_session = boto3.session.Session(
            aws_access_key_id=c.AWS_ACCESS_KEY,
            aws_secret_access_key=c.AWS_SECRET_KEY
        )

        self.client = aws_session.client(
            service_name=c.AWS_SECRET_SERVICE_NAME,
            region_name=c.AWS_REGION
        )

        self.session_expiration = datetime.now() + timedelta(hours=6)

    def get_secret(self, secret_name):
        import json
        from botocore.exceptions import ClientError

        if not self.client:
            self.start_session()

        try:
            get_secret_value_response = self.client.get_secret_value(
                SecretId=secret_name
            )
        except ClientError as e:
            if e.response['Error']['Code'] == 'DecryptionFailureException':
                # Secrets Manager can't decrypt the protected secret text using the provided KMS key.
                log.error("Retrieving secret error: Wrong KMS key ({}).".format(str(e)))
                return
            elif e.response['Error']['Code'] == 'InternalServiceErrorException':
                # An error occurred on the server side.
                log.error("Retrieving secret error: Server error ({}).".format(str(e)))
                return
            elif e.response['Error']['Code'] == 'InvalidParameterException':
                # You provided an invalid value for a parameter.
                log.error("Retrieving secret error: Invalid parameter ({}).".format(str(e)))
                return
            elif e.response['Error']['Code'] == 'InvalidRequestException':
                # You provided a parameter value that is not valid for the current state of the resource.
                log.error("Retrieving secret error: Invalid parameter ({}).".format(str(e)))
                return
            elif e.response['Error']['Code'] == 'ResourceNotFoundException':
                # We can't find the resource that you asked for.
                log.error("Retrieving secret error: Resource not found ({}).".format(str(e)))
                return
        else:
            # Decrypts secret using the associated KMS key.
            if 'SecretString' in get_secret_value_response:
                secret = json.loads(get_secret_value_response['SecretString'])
            else:
                log.error("Could not retrieve secret from AWS, instead we got: {}".format(str(secret)))
                return

            return secret
        log.error("Could not retrieve secret from AWS. Is the secret name (\"{}\") correct?".format(secret_name))

    def get_all_secrets(self):
        self.get_signnow_secret()

    def get_signnow_secret(self):
        if not c.AWS_SIGNNOW_SECRET_NAME:
            return

        signnow_secret = self.get_secret(c.AWS_SIGNNOW_SECRET_NAME)
        if signnow_secret:
            c.SIGNNOW_CLIENT_ID = signnow_secret.get('CLIENT_ID', '') or c.SIGNNOW_CLIENT_ID
            c.SIGNNOW_CLIENT_SECRET = signnow_secret.get('CLIENT_SECRET', '') or c.SIGNNOW_CLIENT_SECRET
            return signnow_secret

def get_config_files(plugin_name, module_dir):
    config_files_str = os.environ.get(f"{plugin_name.upper()}_CONFIG_FILES", "")
    absolute_config_files = []
    if config_files_str:
        config_files = [pathlib.Path(x) for x in config_files_str.split(";")]
        for path in config_files:
            if path.is_absolute():
                if not path.exists():
                    raise ValueError(f"Config file {path} specified in {plugin_name.upper()}_CONFIG_FILES does not exist!")
                absolute_config_files.append(path)
            else:
                if not (module_dir.parents[0] / path).exists():
                    raise ValueError(f"Config file {module_dir.parents[0] / path} specified in {plugin_name.upper()}_CONFIG_FILES does not exist!")
                absolute_config_files.append(module_dir.parents[0] / path)
    return absolute_config_files

def normalize_name(name):
    return name.replace(".", "_")

def load_section_from_environment(path, section):
    """
    Looks for configuration in environment variables. 
    
    Args:
        path (str): The prefix of the current config section. For example,
            uber.ini:
                [cherrypy]
                server.thread_pool: 10
            would translate to uber_cherrypy_server.thread_pool
        section (configobj.ConfigObj): The section of the configspec to search
            for the current path in.
    """
    config = {}
    for setting in section:
        if setting == "__many__":
            prefix = f"{path}_"
            for envvar in os.environ:
                if envvar.startswith(prefix) and not envvar.split(prefix, 1)[1] in [normalize_name(x) for x in section]:
                    config[envvar.split(prefix, 1)[1]] = os.environ[envvar]
        else:
            if isinstance(section[setting], configobj.Section):
                child_path = f"{path}_{setting}"
                child = load_section_from_environment(child_path, section[setting])
                if child:
                    config[setting] = child
            else:
                name = normalize_name(f"{path}_{setting}")
                if name in os.environ:
                    config[setting] = yaml.safe_load(os.environ.get(normalize_name(name)))
    return config

def parse_config(plugin_name, module_dir):
    specfile = module_dir / 'configspec.ini'
    spec = configobj.ConfigObj(str(specfile), interpolation=False, list_values=False, encoding='utf-8', _inspec=True)

    # to allow more/better interpolations
    root_conf = ['root = "{}"\n'.format(module_dir.parents[0]), 'module_root = "{}"\n'.format(module_dir)]
    temp_config = configobj.ConfigObj(root_conf, interpolation=False, encoding='utf-8')

    for config_path in get_config_files(plugin_name, module_dir):
        # this gracefully handles nonexistent files
        file_config = configobj.ConfigObj(str(config_path), encoding='utf-8', interpolation=False)
        if os.environ.get("LOG_CONFIG", "false").lower() == "true":
            print(f"File config for {plugin_name} from {config_path}")
            print(json.dumps(file_config, indent=2, sort_keys=True))
        temp_config.merge(file_config)

    environment_config = load_section_from_environment(plugin_name, spec)
    if os.environ.get("LOG_CONFIG", "false").lower() == "true":
        print(f"Environment config for {plugin_name}")
        print(json.dumps(environment_config, indent=2, sort_keys=True))
    temp_config.merge(configobj.ConfigObj(environment_config, encoding='utf-8', interpolation=False))

    # combining the merge files to one file helps configspecs with interpolation
    with NamedTemporaryFile(delete=False) as config_outfile:
        temp_config.write(config_outfile)
        temp_name = config_outfile.name

    config = configobj.ConfigObj(temp_name, encoding='utf-8', configspec=spec)

    validation = config.validate(validate.Validator(), preserve_errors=True)
    os.unlink(temp_name)

    if validation is not True:
        raise RuntimeError('configuration validation error(s) (): {!r}'.format(
            configobj.flatten_errors(config, validation))
        )

    return config


c = Config()
_config = parse_config("uber", pathlib.Path("/app/uber"))  # outside this module, we use the above c global instead of using this directly
db_connection_string = os.environ.get('DB_CONNECTION_STRING')

for conf, val in _config['secret'].items():
    conf_env = os.environ.get(conf.upper())

    if conf_env is not None:
        setattr(c, conf.upper(), conf_env)
    elif conf == "sqlalchemy_url" and db_connection_string is not None:  # Backwards compatibility
        setattr(c, conf.upper(), db_connection_string)
    else:
        setattr(c, conf.upper(), val)

if c.AWS_SECRET_SERVICE_NAME:
    AWSSecretFetcher().get_all_secrets()

signnow_python_sdk.Config(client_id=c.SIGNNOW_CLIENT_ID,
                          client_secret=c.SIGNNOW_CLIENT_SECRET,
                          environment=c.SIGNNOW_ENV)
signnow_sdk = signnow_python_sdk


def _unrepr(d):
    for opt in d:
        val = d[opt]
        if val in ['True', 'False']:
            d[opt] = ast.literal_eval(val)
        elif isinstance(val, str) and val.isdigit():
            d[opt] = int(val)
        elif isinstance(d[opt], dict):
            _unrepr(d[opt])


_unrepr(_config['appconf'])
c.APPCONF = _config['appconf'].dict()
c.SENTRY = _config['sentry'].dict()
c.HSTS = _config['hsts'].dict()
c.REDISCONF = _config['redis'].dict()
c.REDIS_PREFIX = c.REDISCONF['prefix']
c.REDIS_STORE = redis.Redis(host=c.REDISCONF['host'], port=c.REDISCONF['port'],
                            db=c.REDISCONF['db'], decode_responses=True)

c.BADGE_PRICES = _config['badge_prices']
for _opt, _val in chain(_config.items(), c.BADGE_PRICES.items()):
    if not isinstance(_val, dict) and not hasattr(c, _opt.upper()):
        setattr(c, _opt.upper(), _val)
for _opt, _val in c.BADGE_PRICES['stocks'].items():
    _opt = _opt.upper() + '_STOCK'
    if not hasattr(c, _opt):
        setattr(c, _opt, _val)

c.DATES = {}
c.TIMESTAMP_FORMAT = '%Y-%m-%d %H:%M:%S'
c.DATE_FORMAT = '%Y-%m-%d'
c.EVENT_TIMEZONE = pytz.timezone(c.EVENT_TIMEZONE)
c.make_dates(_config['dates'])

c.DATA_DIRS = {}
c.make_data_dirs(_config['data_dirs'])

if "sqlite" in c.SQLALCHEMY_URL:
    # SQLite does not suport pool_size and max_overflow,
    # so disable them if sqlite is used.
    c.SQLALCHEMY_POOL_SIZE = -1
    c.SQLALCHEMY_MAX_OVERFLOW = -1

# Set database connections to recycle after 10 minutes
c.SQLALCHEMY_POOL_RECYCLE = 3600

c.PRICE_BUMPS = {}
c.PRICE_LIMITS = {}
for _opt, _val in c.BADGE_PRICES['attendee'].items():
    try:
        if ' ' in _opt:
            price_date = c.EVENT_TIMEZONE.localize(datetime.strptime(_opt, '%Y-%m-%d %H%M'))
        else:
            price_date = c.EVENT_TIMEZONE.localize(datetime.strptime(_opt, '%Y-%m-%d'))
    except ValueError:
        c.PRICE_LIMITS[int(_opt)] = _val
    else:
        c.PRICE_BUMPS[price_date] = _val
c.ORDERED_PRICE_LIMITS = sorted([val for key, val in c.PRICE_LIMITS.items()])


# Under certain conditions, we want to completely remove certain payment options from the system.
# However, doing so cleanly also risks an exception being raised if these options are referenced elsewhere in the code
# (i.e., c.STRIPE). So we create an enum val to allow code to check for these variables without exceptions.
if not c.KIOSK_CC_ENABLED and 'stripe' in _config['enums']['door_payment_method']:
    del _config['enums']['door_payment_method']['stripe']
    c.create_enum_val('stripe')

if c.ONLY_PREPAY_AT_DOOR:
    del _config['enums']['door_payment_method']['cash']
    del _config['enums']['door_payment_method']['manual']
    c.create_enum_val('cash')
    c.create_enum_val('manual')

c.make_enums(_config['enums'])

c.make_integer_enums(_config['integer_enums'])

c.BADGE_RANGES = {}
for _badge_type, _range in _config['badge_ranges'].items():
    c.BADGE_RANGES[getattr(c, _badge_type.upper())] = _range

c.BADGE_TYPE_PRICES = {}
for _badge_type, _price in _config['badge_type_prices'].items():
    try:
        c.BADGE_TYPE_PRICES[getattr(c, _badge_type.upper())] = _price
    except AttributeError:
        pass

c.MAX_BADGE_TYPE_UPGRADE = sorted(c.BADGE_TYPE_PRICES, key=c.BADGE_TYPE_PRICES.get,
                                  reverse=True)[0] if c.BADGE_TYPE_PRICES else None

c.make_enum('age_group', OrderedDict([(name, section['desc']) for name, section in _config['age_groups'].items()]))
c.AGE_GROUP_CONFIGS = {}
for _name, _section in _config['age_groups'].items():
    _val = getattr(c, _name.upper())
    c.AGE_GROUP_CONFIGS[_val] = dict(_section.dict(), val=_val)
c.AGE_GROUP_OPTS = [(key, value['desc']) for key,value in c.AGE_GROUP_CONFIGS.items()]

c.RECEIPT_DEPT_CATEGORIES = {}
for _name, _val in _config['enums']['receipt_item_dept'].items():
    _val = getattr(c, _name.upper())
    c.RECEIPT_DEPT_CATEGORIES[_val] = {getattr(c, key.upper()): val for key, val in _config['enums'][_name].items()}

c.TABLE_PRICES = defaultdict(lambda: _config['table_prices']['default_price'],
                             {int(k): v for k, v in _config['table_prices'].items() if k != 'default_price'})

# Let admins remove door payment methods by making their label blank
c.DOOR_PAYMENT_METHOD_OPTS = [opt for opt in c.DOOR_PAYMENT_METHOD_OPTS if opt[1]]
c.DOOR_PAYMENT_METHODS = {key: val for key, val in c.DOOR_PAYMENT_METHODS.items() if val}

c.TERMINAL_ID_TABLE = {k.lower().replace('-', ''): v for k, v in _config['secret']['terminal_ids'].items()}

c.SHIFTLESS_DEPTS = {getattr(c, dept.upper()) for dept in c.SHIFTLESS_DEPTS}
c.PREASSIGNED_BADGE_TYPES = [getattr(c, badge_type.upper()) for badge_type in c.PREASSIGNED_BADGE_TYPES]
c.TRANSFERABLE_BADGE_TYPES = [getattr(c, badge_type.upper()) for badge_type in c.TRANSFERABLE_BADGE_TYPES]

c.MIVS_CHECKLIST = _config['mivs_checklist']
for key, val in c.MIVS_CHECKLIST.items():
    val['deadline'] = c.EVENT_TIMEZONE.localize(datetime.strptime(val['deadline'] + ' 23:59', '%Y-%m-%d %H:%M'))
    if val['start']:
        val['start'] = c.EVENT_TIMEZONE.localize(datetime.strptime(val['start'] + ' 23:59', '%Y-%m-%d %H:%M'))

c.DEPT_HEAD_CHECKLIST = {key: val for key, val in _config['dept_head_checklist'].items() if val['deadline']}

c.CON_LENGTH = int((c.ESCHATON - c.EPOCH).total_seconds() // 3600)
c.START_TIME_OPTS = [
    (dt, dt.strftime('%I %p %a')) for dt in (c.EPOCH + timedelta(hours=i) for i in range(c.CON_LENGTH))]

c.SETUP_JOB_START = c.EPOCH - timedelta(days=c.SETUP_SHIFT_DAYS)
c.TEARDOWN_JOB_END = c.ESCHATON + timedelta(days=1, hours=23)  # Allow two full days for teardown shifts
c.CON_TOTAL_DAYS = -(-(int((c.TEARDOWN_JOB_END - c.SETUP_JOB_START).total_seconds() // 3600)) // 24)
c.PANEL_STRICT_LENGTH_OPTS = [opt for opt in c.PANEL_LENGTH_OPTS if opt != c.OTHER]

c.EVENT_YEAR = c.EPOCH.strftime('%Y')
c.EVENT_NAME_AND_YEAR = c.EVENT_NAME + (' {}'.format(c.EVENT_YEAR) if c.EVENT_YEAR else '')
c.EVENT_MONTH = c.EPOCH.strftime('%B')
c.EVENT_START_DAY = int(c.EPOCH.strftime('%d')) % 100
c.EVENT_END_DAY = int(c.ESCHATON.strftime('%d')) % 100
c.SHIFTS_START_DAY = c.EPOCH - timedelta(days=c.SETUP_SHIFT_DAYS)

c.DAYS = sorted({(dt.strftime('%Y-%m-%d'), dt.strftime('%a')) for dt, desc in c.START_TIME_OPTS})
c.HOURS = ['{:02}'.format(i) for i in range(24)]
c.MINUTES = ['{:02}'.format(i) for i in range(60)]

c.DAYS_OF_WEEK = {'Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'}
if c.ONE_DAYS_ENABLED and c.PRESELL_ONE_DAYS:
    _day = c.EPOCH.date()
    while _day <= c.ESCHATON.date():
        _name = _day.strftime('%A')
        _val = c.create_enum_val(_name)
        c.BADGES[_val] = _name
        c.BADGE_OPTS.append((_val, _name))
        c.BADGE_VARS.append(_name.upper())
        c.BADGE_RANGES[_val] = c.BADGE_RANGES[c.ONE_DAY_BADGE]
        if c.ONE_DAY_BADGE in c.TRANSFERABLE_BADGE_TYPES:
            c.TRANSFERABLE_BADGE_TYPES.append(_val)
        if c.ONE_DAY_BADGE in c.PREASSIGNED_BADGE_TYPES:
            c.PREASSIGNED_BADGE_TYPES.append(_val)
        _day += timedelta(days=1)

c.COUNTRY_OPTS = []
c.COUNTRY_ALT_SPELLINGS = {}
for country in list(pycountry.countries):
    insert_idx = None
    country_name = country.name if "Taiwan" not in country.name else "Taiwan"
    country_dict = country.__dict__['_fields']
    alt_spellings = [val for val in map(lambda x: country_dict.get(x), ['alpha_2', 'common_name']) if val]
    if country_name == 'United States':
        alt_spellings.extend(["USA", "United States of America"])
        insert_idx = 0
    elif country_name == 'United Kingdom':
        alt_spellings.extend(["Great Britain", "England", "UK", "Wales", "Scotland", "Northern Ireland"])
        insert_idx = 2
    elif country_name == 'Canada':
        insert_idx = 1

    opt = {'value': country_name, 'label': country_name, 'alt_spellings': " ".join(alt_spellings)}
    if insert_idx is not None:
        c.COUNTRY_OPTS.insert(insert_idx, opt)
    else:
        c.COUNTRY_OPTS.append(opt)


c.REGION_OPTS_US = sorted([{'value': region.name, 'label': region.name, 'alt_spellings': region.code[2:]
      } for region in list(pycountry.subdivisions.get(country_code='US'))], key=lambda x: x['label'])
c.REGION_OPTS_CANADA = sorted([{'value': region.name, 'label': region.name, 'alt_spellings': region.code[2:]
      } for region in list(pycountry.subdivisions.get(country_code='CA'))], key=lambda x: x['label'])

c.MAX_BADGE = max(xs[1] for xs in c.BADGE_RANGES.values())

c.JOB_PAGE_OPTS = (
    ('index', 'Calendar View'),
    ('signups', 'Signups View'),
    ('staffers', 'Staffer Summary'),
)
c.WEIGHT_OPTS = (
    ('0.5', 'x0.5'),
    ('1.0', 'x1.0'),
    ('1.5', 'x1.5'),
    ('2.0', 'x2.0'),
)
c.JOB_DEFAULTS = ['name', 'description', 'duration', 'slots', 'weight', 'visibility', 'required_roles_ids', 'extra15']

c.PREREG_SHIRT_OPTS = sorted(c.PREREG_SHIRT_OPTS if c.PREREG_SHIRT_OPTS else c.SHIRT_OPTS)[1:]
c.PREREG_SHIRTS = {key: val for key, val in c.PREREG_SHIRT_OPTS}
c.STAFF_SHIRT_OPTS = sorted(c.STAFF_SHIRT_OPTS if len(c.STAFF_SHIRT_OPTS) > 1 else c.SHIRT_OPTS)
c.SHIRT_OPTS = sorted(c.SHIRT_OPTS)
shirt_label_lookup = {val: key for key, val in c.SHIRT_OPTS}
c.SHIRT_SIZE_STOCKS = {shirt_label_lookup[val]: key for key, val in c.SHIRT_STOCK_OPTS}

c.DONATION_TIER_OPTS = [(amt, '+ ${}: {}'.format(amt, desc) if amt else desc) for amt, desc in c.DONATION_TIER_OPTS]

c.DONATION_TIER_ITEMS = {}
c.DONATION_TIER_DESCRIPTIONS = _config.get('donation_tier_descriptions', {})
for _ident, _tier in c.DONATION_TIER_DESCRIPTIONS.items():
    try:
        [price] = [amt for amt, name in c.DONATION_TIERS.items() if name == _tier['name']]
    except ValueError:
        pass

    _tier['value'] = price
    _tier['price'] = price
    if price:  # ignore the $0 kickin level
        c.DONATION_TIER_ITEMS[price] = _tier['merch_items'] or _tier['description'].split('|')

c.STORE_ITEM_NAMES = [desc for val, desc in c.STORE_PRICE_OPTS]
c.FEE_ITEM_NAMES = [desc for val, desc in c.FEE_PRICE_OPTS]

c.WRISTBAND_COLORS = defaultdict(lambda: c.WRISTBAND_COLORS[c.DEFAULT_WRISTBAND], c.WRISTBAND_COLORS)

c.SAME_NUMBER_REPEATED = r'^(\d)\1+$'

c.HOTEL_LOTTERY = _config.get('hotel_lottery', {})
for key in ["hotels", "room_types", "suite_room_types", "priorities"]:
    opts = []
    for name, item in c.HOTEL_LOTTERY.get(key, {}).items():
        if isinstance(item, dict):
            item.__hash__ = lambda x: hash(x.name + x.description)
            base_key = f"HOTEL_LOTTERY_{name.upper()}"
            dict_key = int(sha512(base_key.encode()).hexdigest()[:7], 16)
            setattr(c, base_key, dict_key)
            opts.append((dict_key, item))
    setattr(c, f"HOTEL_LOTTERY_{key.upper()}_OPTS", opts)

# Allows 0-9, a-z, A-Z, and a handful of punctuation characters
c.VALID_BADGE_PRINTED_CHARS = r'[a-zA-Z0-9!"#$%&\'()*+,\-\./:;<=>?@\[\\\]^_`\{|\}~ "]'
c.EVENT_QR_ID = c.EVENT_QR_ID or c.EVENT_NAME_AND_YEAR.replace(' ', '_').lower()
c.update_name_problems()

try:
    _items = sorted([int(step), url] for step, url in _config['volunteer_checklist'].items() if url)
except ValueError:
    log.error('[volunteer_checklist] config options must have integer option names')
    raise
else:
    c.VOLUNTEER_CHECKLIST = [url for step, url in _items]

if not c.AUTHORIZENET_LOGIN_ID:
    import stripe
    stripe.api_key = c.STRIPE_SECRET_KEY


# plugins can use this to append paths which will be included as <script> tags, e.g. if a plugin
# appends '../static/foo.js' to this list, that adds <script src="../static/foo.js"></script> to
# all of the pages on the site except for preregistration pages (for performance)
c.JAVASCRIPT_INCLUDES = []

# If receiving static content from a CDN, define a dictionary of strings where the key is the
# relative URL of the resource (e.g., theme/prereg.css) and the value is the hash for that resource
c.STATIC_HASH_LIST = {}

if not c.ALLOW_SHARED_TABLES:
    c.DEALER_STATUS_OPTS = [(key, val) for key, val in c.DEALER_STATUS_OPTS if key != c.SHARED]
dealer_status_label_lookup = {val: key for key, val in c.DEALER_STATUS_OPTS}
c.DEALER_EDITABLE_STATUSES = [dealer_status_label_lookup[name] for name in c.DEALER_EDITABLE_STATUS_LIST]
c.DEALER_CANCELLABLE_STATUSES = [dealer_status_label_lookup[name] for name in c.DEALER_CANCELLABLE_STATUS_LIST]
c.DEALER_ACCEPTED_STATUSES = [c.APPROVED, c.SHARED] if c.ALLOW_SHARED_TABLES else [c.APPROVED]


# A list of models that have properties defined for exporting for Guidebook
c.GUIDEBOOK_MODELS = [
    ('GuestGroup_guest', 'Guest'),
    ('GuestGroup_band', 'Band'),
    ('MITSGame', 'MITS'),
    ('IndieGame', 'MIVS'),
    ('Group_dealer', 'Marketplace'),
]


# A list of properties that we will check for when export for Guidebook
# and the column headings Guidebook expects for them
c.GUIDEBOOK_PROPERTIES = [
    ('guidebook_name', 'Name'),
    ('guidebook_subtitle', 'Sub-Title (i.e. Location, Table/Booth, or Title/Sponsorship Level)'),
    ('guidebook_desc', 'Description (Optional)'),
    ('guidebook_location', 'Location/Room'),
    ('guidebook_header', 'Image (Optional)'),
    ('guidebook_thumbnail', 'Thumbnail (Optional)'),
]


# =============================
# hotel
# =============================

c.NIGHT_NAMES = [name.lower() for name in c.NIGHT_VARS]
c.NIGHT_DISPLAY_ORDER = [getattr(c, night.upper()) for night in c.NIGHT_DISPLAY_ORDER]

c.NIGHT_DATES = {c.ESCHATON.strftime('%A'): c.ESCHATON.date()}

c.CORE_NIGHTS = []
_day = c.EPOCH
while _day.date() != c.ESCHATON.date():
    c.NIGHT_DATES[_day.strftime('%A')] = _day.date()
    c.CORE_NIGHTS.append(getattr(c, _day.strftime('%A').upper()))
    _day += timedelta(days=1)

for _before in range(1, 4):
    _day = c.EPOCH.date() - timedelta(days=_before)
    c.NIGHT_DATES[_day.strftime('%A')] = _day

c.SETUP_NIGHTS = c.NIGHT_DISPLAY_ORDER[:c.NIGHT_DISPLAY_ORDER.index(c.CORE_NIGHTS[0])]
c.TEARDOWN_NIGHTS = c.NIGHT_DISPLAY_ORDER[1 + c.NIGHT_DISPLAY_ORDER.index(c.CORE_NIGHTS[-1]):]

for _attr in ['CORE_NIGHT', 'SETUP_NIGHT', 'TEARDOWN_NIGHT']:
    setattr(c, _attr + '_NAMES', [c.NIGHTS[night] for night in getattr(c, _attr + 'S')])


# =============================
# attendee_tournaments
#
# NO LONGER USED.
#
# The attendee_tournaments module is no longer used, but has been
# included for backward compatibility with legacy servers.
# =============================

c.TOURNAMENT_AVAILABILITY_OPTS = []
_val = 0
for _day in range((c.ESCHATON - c.EPOCH).days):
    for _when in ['Morning (8am-12pm)', 'Afternoon (12pm-6pm)', 'Evening (6pm-10pm)', 'Night (10pm-2am)']:
        c.TOURNAMENT_AVAILABILITY_OPTS.append([
            _val,
            _when + ' of ' + (c.EPOCH + timedelta(days=_day)).strftime('%A %B %d')
        ])
        _val += 1
c.TOURNAMENT_AVAILABILITY_OPTS.append([_val, 'Morning (8am-12pm) of ' + c.ESCHATON.strftime('%A %B %d')])


# =============================
# mivs
# =============================

c.MIVS_CODES_REQUIRING_INSTRUCTIONS = [
    getattr(c, code_type.upper()) for code_type in c.MIVS_CODES_REQUIRING_INSTRUCTIONS]

# c.MIVS_INDIE_JUDGE_GENRE* should be the same as c.MIVS_INDIE_GENRE* but with a c.MIVS_ALL_GENRES option
_mivs_all_genres_desc = 'All genres'
c.create_enum_val('mivs_all_genres')
c.make_enum('mivs_indie_judge_genre', _config['enums']['mivs_indie_genre'])
c.MIVS_INDIE_JUDGE_GENRES[c.MIVS_ALL_GENRES] = _mivs_all_genres_desc
c.MIVS_INDIE_JUDGE_GENRE_OPTS.insert(0, (c.MIVS_ALL_GENRES, _mivs_all_genres_desc))

c.MIVS_PROBLEM_STATUSES = {getattr(c, status.upper()) for status in c.MIVS_PROBLEM_STATUSES.split(',')}

c.FINAL_MIVS_GAME_STATUSES = [c.ACCEPTED, c.WAITLISTED, c.DECLINED, c.CANCELLED]

# used for computing the difference between the "drop-dead deadline" and the "soft deadline"
c.SOFT_MIVS_JUDGING_DEADLINE = c.MIVS_JUDGING_DEADLINE - timedelta(days=7)

# Automatically generates all the previous MIVS years based on the eschaton and c.MIVS_START_YEAR
c.PREV_MIVS_YEAR_OPTS, c.PREV_MIVS_YEARS = [], {}
for num in range(c.ESCHATON.year - c.MIVS_START_YEAR):
    val = c.MIVS_START_YEAR + num
    desc = c.EVENT_NAME + ' MIVS ' + str(val)
    c.PREV_MIVS_YEAR_OPTS.append((val, desc))
    c.PREV_MIVS_YEARS[val] = desc


# =============================
# mits
# =============================

# The number of steps to the MITS application process.  Since changing this requires a code change
# anyway (in order to add another step), this is hard-coded here rather than being a config option.
c.MITS_APPLICATION_STEPS = 4

c.MITS_DESC_BY_AGE = {age: c.MITS_AGE_DESCRIPTIONS[age] for age in c.MITS_AGES}

# =============================
# panels
# =============================

c.PANEL_SCHEDULE_DAYS = math.ceil((c.PANELS_ESCHATON - c.PANELS_EPOCH.replace(hour=0)).total_seconds() / 86400)
c.PANEL_SCHEDULE_LENGTH = int((c.PANELS_ESCHATON - c.PANELS_EPOCH).total_seconds() // 3600)
c.EVENT_START_TIME_OPTS = [(dt, dt.strftime('%I %p %a') if not dt.minute else dt.strftime('%I:%M %a'))
                           for dt in [c.EPOCH + timedelta(minutes=i * 30) for i in range(c.PANEL_SCHEDULE_LENGTH)]]
c.EVENT_DURATION_OPTS = [(i, '%.1f hour%s' % (i/2, 's' if i != 2 else '')) for i in range(1, 19)]

c.ORDERED_EVENT_LOCS = [loc for loc, desc in c.EVENT_LOCATION_OPTS]
c.EVENT_BOOKED = {'colspan': 0}
c.EVENT_OPEN = {'colspan': 1}

c.PRESENTATION_OPTS.sort(key=lambda tup: 'zzz' if tup[0] == c.OTHER else tup[1])


def _make_room_trie(rooms):
    root = nesteddefaultdict()
    for index, (location, description) in enumerate(rooms):
        for word in filter(lambda s: s, re.split(r'\W+', description)):
            current_dict = root
            current_dict['__rooms__'][location] = index
            for letter in word:
                current_dict = current_dict.setdefault(letter.lower(), nesteddefaultdict())
                current_dict['__rooms__'][location] = index
    return root


c.ROOM_TRIE = _make_room_trie(c.EVENT_LOCATION_OPTS)

invalid_rooms = [room for room in (c.PANEL_ROOMS + c.MUSIC_ROOMS) if not getattr(c, room.upper(), None)]

for room in invalid_rooms:
    log.warning('config: panels_room config problem: '
                'Ignoring {!r} because it was not also found in [[event_location]] section.'.format(room.upper()))

c.PANEL_ROOMS = [getattr(c, room.upper()) for room in c.PANEL_ROOMS if room not in invalid_rooms]
c.MUSIC_ROOMS = [getattr(c, room.upper()) for room in c.MUSIC_ROOMS if room not in invalid_rooms]


# =============================
# tabletop
# =============================

invalid_tabletop_rooms = [room for room in c.TABLETOP_LOCATIONS if not getattr(c, room.upper(), None)]
for room in invalid_tabletop_rooms:
    log.warning('config: tabletop_locations config problem: '
                'Ignoring {!r} because it was not also found in [[event_location]] section.'.format(room.upper()))

c.TABLETOP_LOCATIONS = [getattr(c, room.upper()) for room in c.TABLETOP_LOCATIONS if room not in invalid_tabletop_rooms]


# =============================
# guests
# =============================

c.ROCK_ISLAND_GROUPS = [getattr(c, group.upper()) for group in c.ROCK_ISLAND_GROUPS if group or group.strip()]

# A list of checklist items for display on the guest group admin page
c.GUEST_CHECKLIST_ITEMS = [
    {'name': 'bio', 'header': 'Announcement Info Provided'},
    {'name': 'performer_badges', 'header': 'Performer Badges'},
    {'name': 'panel', 'header': 'Panel'},
    {'name': 'autograph'},
    {'name': 'info', 'header': 'Agreement Completed'},
    {'name': 'merch', 'header': 'Merch'},
    {'name': 'interview'},
    {'name': 'mc', 'header': 'MC'},
    {'name': 'stage_plot', 'header': 'Stage Plans', 'is_link': True},
    {'name': 'rehearsal'},
    {'name': 'taxes', 'header': 'W9 Uploaded', 'is_link': True},
    {'name': 'badges', 'header': 'Badges Claimed'},
    {'name': 'hospitality'},
    {'name': 'travel_plans'},
    {'name': 'charity', 'header': 'Charity'},
]

# Generate the possible template prefixes per step
for item in c.GUEST_CHECKLIST_ITEMS:
    item['deadline_template'] = ['guest_checklist/', item['name'] + '_deadline.html']

c.SAML_SETTINGS = {}
if c.SAML_SP_SETTINGS["privateKey"]:
    sp_settings = {
            "entityId": c.URL_BASE + "/saml/metadata",
            "assertionConsumerService": {
                "url": c.URL_BASE + "/saml/acs",
                "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST"
            },
            "singleLogoutService": {
                "url": c.URL_BASE + "/saml/logout",
                "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect"
            },
            "NameIDFormat": "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress",
            "x509cert": c.SAML_SP_SETTINGS["x509cert"],
            "privateKey": c.SAML_SP_SETTINGS["privateKey"]
        }
    c.SAML_SETTINGS["idp"] = c.SAML_IDP_SETTINGS
    c.SAML_SETTINGS["sp"] = sp_settings
    if c.DEV_BOX:
        c.SAML_SETTINGS["debug"] = True
    else:
        c.SAML_SETTINGS["strict"] = True
