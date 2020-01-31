import ast
import decimal
import hashlib
import inspect
import os
import pytz
import re
import uuid
from collections import defaultdict, OrderedDict
from datetime import date, datetime, time, timedelta
from hashlib import sha512
from itertools import chain

import cherrypy
import stripe
from pockets import keydefaultdict, nesteddefaultdict, unwrap
from pockets.autolog import log
from sideboard.lib import cached_property, parse_config, request_cached_property
from sqlalchemy import or_
from sqlalchemy.orm import joinedload, subqueryload

import uber


def dynamic(func):
    setattr(func, '_dynamic', True)
    return func


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

        if 'dates' in plugin_config:
            self.make_dates(plugin_config['dates'])

        if 'data_dirs' in plugin_config:
            self.make_data_dirs(plugin_config['data_dirs'])

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
            if not dt and not c.AT_THE_CON:
                badges_sold = self.BADGES_SOLD

                for badge_cap, bumped_price in sorted(self.PRICE_LIMITS.items()):
                    if badges_sold >= badge_cap and bumped_price > price:
                        price = bumped_price
        return price

    def get_group_price(self, dt=None):
        return self.get_attendee_price(dt) - self.GROUP_DISCOUNT

    def get_badge_count_by_type(self, badge_type):
        """
        Returns the count of all badges of the given type that we've promised to
        attendees.  This counts uncompleted placeholder badges but NOT unpaid
        badges, since those have by definition not been promised to anyone.
        """
        from uber.models import Session, Attendee
        with Session() as session:
            return session.query(Attendee).filter(
                Attendee.paid != c.NOT_PAID,
                Attendee.badge_type == badge_type,
                Attendee.badge_status.in_([c.COMPLETED_STATUS, c.NEW_STATUS])).count()

    def get_printed_badge_deadline_by_type(self, badge_type):
        """
        Returns either PRINTED_BADGE_DEADLINE for custom badge types or the latter of PRINTED_BADGE_DEADLINE and
        SUPPORTER_BADGE_DEADLINE if the badge type is not preassigned (and only has a badge name if they're a supporter)
        """
        return c.PRINTED_BADGE_DEADLINE if badge_type in c.PREASSIGNED_BADGE_TYPES \
            else max(c.PRINTED_BADGE_DEADLINE, c.SUPPORTER_BADGE_DEADLINE)

    def after_printed_badge_deadline_by_type(self, badge_type):
        return uber.utils.localized_now() > self.get_printed_badge_deadline_by_type(badge_type)

    def has_section_or_page_access(self, include_read_only=False, page_path=''):
        access = uber.models.AdminAccount.get_access_set(include_read_only=include_read_only)
        page_path = page_path or self.PAGE_PATH

        section = page_path.replace(page_path.split('/')[-1], '').strip('/')

        section_and_page = page_path.strip('/').replace('/', '_')
        if page_path.endswith('/'):
            section_and_page += "_index"

        if section_and_page in access or section in access:
            return True

    @property
    def DEALER_REG_OPEN(self):
        return self.AFTER_DEALER_REG_START and self.BEFORE_DEALER_REG_SHUTDOWN

    @property
    @dynamic
    def DEALER_REG_SOFT_CLOSED(self):
        return self.AFTER_DEALER_REG_DEADLINE or self.DEALER_APPS >= self.MAX_DEALER_APPS \
            if self.MAX_DEALER_APPS else self.AFTER_DEALER_REG_DEADLINE
            
    @property
    def ART_SHOW_OPEN(self):
        return self.AFTER_ART_SHOW_REG_START and self.BEFORE_ART_SHOW_DEADLINE

    @property
    def SELF_SERVICE_REFUNDS_OPEN(self):
        return self.BEFORE_REFUND_CUTOFF and (self.AFTER_REFUND_START or not self.REFUND_START)

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
        c.ATTENDEE_BADGE_COUNT is already provided via getattr, but redefining it here lets us cache it per request.
        """
        return self.get_badge_count_by_type(c.ATTENDEE_BADGE)

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
                individuals = attendees.filter(or_(
                    Attendee.paid == self.HAS_PAID,
                    Attendee.paid == self.REFUNDED)
                ).filter(Attendee.badge_status == self.COMPLETED_STATUS).count()

                group_badges = attendees.join(Attendee.group).filter(
                    Attendee.paid == self.PAID_BY_GROUP,
                    Group.amount_paid > 0).count()

                promo_code_badges = session.query(PromoCode).join(PromoCodeGroup).count()

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
    @dynamic
    def SWADGES_AVAILABLE(self):
        """
        TODO: REMOVE THIS AFTER SUPER MAGFEST 2018.

        This property addresses the fact that our "swag badges" (aka swadges)
        arrived more than a day late.  Normally this would have been just a
        normal part of our merch.  However, we now have a bunch of people who
        have already received our merch without the swadge.  So we basically
        have three groups of people:

        1) People who have already received their merch are marked as not
            having received their swadge.

        2) Until the swadges arrive, instead of the "Give Merch" button, we
            want "Give Merch Without Swadge" and "Give Merch Including Swadge"
            buttons.

        3) After the "Give Merch With Swadge" button has been pressed for the
            first time, we want to revert to the single "Give Merch" button,
            which is assumed to include the Swadge because those have arrived.

        This property controls whether we're in state (2) or (3) above.  We
        perform a database query to see if there are any attendees who have
        got_swadge set.  Once we've found that once we cache that result here
        on the "c" object and no longer perform the query.  The reason why we
        do this instead of adding a new config option is to allow us to know
        that the swadges are present without having to restart the server
        during our busiest time of the weekend.
        """
        if getattr(self, '_swadges_available', False):
            return True

        with uber.models.Session() as session:
            got = session.query(uber.models.Attendee).filter_by(got_swadge=True).first()
            if got:
                self._swadges_available = True
            return bool(got)

    @property
    def kickin_availability_matrix(self):
        return dict([[
            getattr(self, level + "_LEVEL"), getattr(self, level + "_AVAILABLE")]
            for level in ['SHIRT', 'SUPPORTER', 'SEASON']
        ])

    @property
    def PREREG_DONATION_OPTS(self):
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
    def PREREG_DONATION_DESCRIPTIONS(self):
        # include only the items that are actually available for purchase
        if not self.SHARED_KICKIN_STOCKS:
            donation_list = [tier for tier in c.DONATION_TIER_DESCRIPTIONS.items()
                             if tier[1]['price'] not in self.kickin_availability_matrix
                             or self.kickin_availability_matrix[tier[1]['price']]]
        elif self.BEFORE_SHIRT_DEADLINE and not self.SHIRT_AVAILABLE:
            donation_list = [tier for tier in c.DONATION_TIER_DESCRIPTIONS.items()
                             if tier[1]['price'] < self.SHIRT_LEVEL]
        elif self.BEFORE_SUPPORTER_DEADLINE and not self.SUPPORTER_AVAILABLE:
            donation_list = [tier for tier in c.DONATION_TIER_DESCRIPTIONS.items()
                             if tier[1]['price'] < self.SUPPORTER_LEVEL]
        elif self.BEFORE_SUPPORTER_DEADLINE and self.SEASON_AVAILABLE:
            donation_list = [tier for tier in c.DONATION_TIER_DESCRIPTIONS.items()
                             if tier[1]['price'] < self.SEASON_LEVEL]
        else:
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
    def PREREG_DONATION_TIERS(self):
        return dict(self.PREREG_DONATION_OPTS)

    @property
    def PREREG_REQUEST_HOTEL_INFO_DEADLINE(self):
        """
        The datetime at which the "Request Hotel Info" checkbox will NO LONGER
        be shown during preregistration.
        """
        return self.PREREG_OPEN + timedelta(
            hours=max(0, self.PREREG_REQUEST_HOTEL_INFO_DURATION))

    @property
    def PREREG_REQUEST_HOTEL_INFO_ENABLED(self):
        """
        Boolean which indicates whether the "Request Hotel Info" checkbox is
        enabled generally, whether or not the deadline has passed.
        """
        return self.PREREG_REQUEST_HOTEL_INFO_DURATION > 0

    @property
    def PREREG_REQUEST_HOTEL_INFO_OPEN(self):
        """
        Boolean which indicates whether the "Request Hotel Info" checkbox is
        enabled and currently open with preregistration.
        """
        if not self.PREREG_REQUEST_HOTEL_INFO_ENABLED:
            return False
        return not self.AFTER_PREREG_REQUEST_HOTEL_INFO_DEADLINE

    @property
    def PREREG_HOTEL_INFO_EMAIL_DATE(self):
        """
        Date at which the hotel booking link email becomes available to send.
        """
        return self.PREREG_REQUEST_HOTEL_INFO_DEADLINE + \
            timedelta(hours=max(0, self.PREREG_HOTEL_INFO_EMAIL_WAIT_DURATION))

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
                opts.append((self.ONE_DAY_BADGE,  'Single Day Badge (${})'.format(self.ONEDAY_BADGE_PRICE)))
        return opts

    @property
    def PREREG_AGE_GROUP_OPTS(self):
        return [opt for opt in self.AGE_GROUP_OPTS if opt[0] != self.AGE_UNKNOWN]

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
    def PAGE_PATH(self):
        return cherrypy.request.path_info

    @property
    def PAGE(self):
        return cherrypy.request.path_info.split('/')[-1]

    @property
    def PATH(self):
        return cherrypy.request.path_info.replace(cherrypy.request.path_info.split('/')[-1], '').strip('/')

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
                attrs = Attendee.to_dict_default_attrs + ['admin_account', 'assigned_depts']
                admin_account = session.query(AdminAccount) \
                    .filter_by(id=cherrypy.session.get('account_id')) \
                    .options(subqueryload(AdminAccount.attendee).subqueryload(Attendee.assigned_depts)).one()

                return admin_account.attendee.to_dict(attrs)
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
            current_admin = session.admin_attendee()
            if getattr(current_admin.admin_account, 'full_shifts_admin', None):
                return [(d.id, d.name) for d in query]
            else:
                return [(d.id, d.name) for d in query if d.id in current_admin.assigned_depts_ids]

    @request_cached_property
    @dynamic
    def DEFAULT_DEPARTMENT_ID(self):
        return list(c.ADMIN_DEPARTMENTS.keys())[0] if c.ADMIN_DEPARTMENTS else 0

    @property
    def DEFAULT_REGDESK_INT(self):
        return getattr(self, 'REGDESK', getattr(self, 'REGISTRATION', 177161930))

    @property
    def DEFAULT_STOPS_INT(self):
        return getattr(self, 'STOPS', 29995679)

    @property
    def HTTP_METHOD(self):
        return cherrypy.request.method.upper()

    def get_kickin_count(self, kickin_level):
        from uber.models import Session, Attendee
        with Session() as session:
            count = session.query(Attendee).filter_by(amount_extra=kickin_level).count()
        return count

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
        
        accessible_site_sections = {section: pages for section, pages in pages.items() 
                                    if c.has_section_or_page_access(page_path=section, include_read_only=True)}
        for section in accessible_site_sections:
            accessible_site_sections[section] = [page for page in accessible_site_sections[section] 
                                                 if c.has_section_or_page_access(page_path=page['path'], include_read_only=True)]
            
        return sorted(accessible_site_sections.items())
    
    @cached_property
    def GETTABLE_SITE_PAGES(self):
        """
        Introspects all available pages in the application and returns several data structures for use in displaying them.
        Returns:
            public_site_sections (list): a list of site sections that are accessible to the public, e.g., 'preregistration'
            public_pages (list): a list of individual pages in non-public site sections that are accessible to the public,
                prepended by their site section; e.g., 'registration_register' for registration/register
            pages (defaultdict(list)): a dictionary with keys corresponding to site sections, each key containing a list
                of key/value pairs for each page inside that section.
                Example: 
                    pages['registration'] = [
                        {'name': 'Arbitrary Charge Form', 'path': '/merch_admin/arbitrary_charge_form'},
                        {'name': 'Comments', 'path': '/registration/comments'},
                        {'name': 'Discount', 'path': '/registration/discount'},
                    ]
        """
        public_site_sections = ['static_views', 'angular', 'public', 'staffing']
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
                                                               or has_defaults and not spec.varkw):
                        pages[module_name].append({
                            'name': name.replace('_', ' ').title(),
                            'path': '/{}/{}'.format(module_name, name)
                        })
        return public_site_sections, public_pages, pages

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
                for a in session.query(AdminAccount)
                                .options(joinedload(AdminAccount.attendee))
                                if 'panels_admin' in a.read_or_write_access_set
            ], key=lambda tup: tup[1], reverse=False)

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
                return access_name[:-5] in c.ADMIN_ACCESS_SET
            return access_name in c.ADMIN_WRITE_ACCESS_SET
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
        elif hasattr(_secret, name):
            return getattr(_secret, name)
        elif name.lower() in _config['secret']:
            return _config['secret'][name.lower()]
        else:
            raise AttributeError('no such attribute {}'.format(name))


class SecretConfig(_Overridable):
    """
    This class is for properties which we don't want to be used as Javascript
    variables.  Properties on this class can be accessed normally through the
    global c object as if they were defined there.
    """

    @property
    def SQLALCHEMY_URL(self):
        """
        support reading the DB connection info from an environment var (used with Docker containers)
        DB_CONNECTION_STRING should contain the full Postgres URI
        """
        db_connection_string = os.environ.get('DB_CONNECTION_STRING')

        if db_connection_string is not None:
            return db_connection_string
        else:
            return _config['secret']['sqlalchemy_url']


c = Config()
_secret = SecretConfig()

_config = parse_config(__file__)  # outside this module, we use the above c global instead of using this directly


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

if "sqlite" in _config['secret']['sqlalchemy_url']:
    # SQLite does not suport pool_size and max_overflow,
    # so disable them if sqlite is used.
    c.SQLALCHEMY_POOL_SIZE = -1
    c.SQLALCHEMY_MAX_OVERFLOW = -1

c.PRICE_BUMPS = {}
c.PRICE_LIMITS = {}
for _opt, _val in c.BADGE_PRICES['attendee'].items():
    try:
        if ' ' in _opt:
            date = c.EVENT_TIMEZONE.localize(datetime.strptime(_opt, '%Y-%m-%d %H%M'))
        else:
            date = c.EVENT_TIMEZONE.localize(datetime.strptime(_opt, '%Y-%m-%d'))
    except ValueError:
        c.PRICE_LIMITS[int(_opt)] = _val
    else:
        c.PRICE_BUMPS[date] = _val
c.ORDERED_PRICE_LIMITS = sorted([val for key, val in c.PRICE_LIMITS.items()])


def _is_intstr(s):
    if s and s[0] in ('-', '+'):
        return s[1:].isdigit()
    return s.isdigit()


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

for _name, _val in _config['integer_enums'].items():
    if isinstance(_val, int):
        setattr(c, _name.upper(), _val)

for _name, _section in _config['integer_enums'].items():
    if isinstance(_section, dict):
        _interpolated = OrderedDict()
        for _desc, _val in _section.items():
            if _is_intstr(_val):
                _price = int(_val)
            else:
                _price = getattr(c, _val.upper())

            _interpolated[_desc] = _price

        c.make_enum(_name, _interpolated, prices=_name.endswith('_price'))

c.BADGE_RANGES = {}
for _badge_type, _range in _config['badge_ranges'].items():
    c.BADGE_RANGES[getattr(c, _badge_type.upper())] = _range

c.BADGE_TYPE_PRICES = {}
for _badge_type, _price in _config['badge_type_prices'].items():
    try:
        c.BADGE_TYPE_PRICES[getattr(c, _badge_type.upper())] = _price
    except AttributeError:
        pass

c.make_enum('age_group', OrderedDict([(name, section['desc']) for name, section in _config['age_groups'].items()]))
c.AGE_GROUP_CONFIGS = {}
for _name, _section in _config['age_groups'].items():
    _val = getattr(c, _name.upper())
    c.AGE_GROUP_CONFIGS[_val] = dict(_section.dict(), val=_val)

c.TABLE_PRICES = defaultdict(lambda: _config['table_prices']['default_price'],
                             {int(k): v for k, v in _config['table_prices'].items() if k != 'default_price'})
c.PREREG_TABLE_OPTS = list(range(1, c.MAX_TABLES + 1))
c.ADMIN_TABLE_OPTS = [decimal.Decimal(x) for x in range(0, 9)]

c.SHIFTLESS_DEPTS = {getattr(c, dept.upper()) for dept in c.SHIFTLESS_DEPTS}
c.DISCOUNTABLE_BADGE_TYPES = [getattr(c, badge_type.upper()) for badge_type in c.DISCOUNTABLE_BADGE_TYPES]
c.PREASSIGNED_BADGE_TYPES = [getattr(c, badge_type.upper()) for badge_type in c.PREASSIGNED_BADGE_TYPES]
c.TRANSFERABLE_BADGE_TYPES = [getattr(c, badge_type.upper()) for badge_type in c.TRANSFERABLE_BADGE_TYPES]

c.MIVS_CHECKLIST = _config['mivs_checklist']
for key, val in c.MIVS_CHECKLIST.items():
    val['deadline'] = c.EVENT_TIMEZONE.localize(datetime.strptime(val['deadline'] + ' 23:59', '%Y-%m-%d %H:%M'))
    if val['start']:
        val['start'] = c.EVENT_TIMEZONE.localize(datetime.strptime(val['start'] + ' 23:59', '%Y-%m-%d %H:%M'))

c.DEPT_HEAD_CHECKLIST = _config['dept_head_checklist']

c.CON_LENGTH = int((c.ESCHATON - c.EPOCH).total_seconds() // 3600)
c.START_TIME_OPTS = [
    (dt, dt.strftime('%I %p %a')) for dt in (c.EPOCH + timedelta(hours=i) for i in range(c.CON_LENGTH))]

c.DURATION_OPTS = [(i, '%i hour%s' % (i, ('s' if i > 1 else ''))) for i in range(1, 9)]
c.SETUP_TIME_OPTS = [
    (dt, dt.strftime('%I %p %a'))
    for dt in (
        c.EPOCH - timedelta(days=day) + timedelta(hours=hour)
        for day in range(c.SETUP_SHIFT_DAYS, 0, -1)
        for hour in range(24))]

c.TEARDOWN_TIME_OPTS = [
    (dt, dt.strftime('%I %p %a'))
    for dt in (
        c.ESCHATON + timedelta(days=day) + timedelta(hours=hour)
        for day in range(0, 2, 1)  # Allow two full days for teardown shifts
        for hour in range(24))]

# code for all time slots
c.CON_TOTAL_LENGTH = int((c.TEARDOWN_TIME_OPTS[-1][0] - c.SETUP_TIME_OPTS[0][0]).seconds / 3600)
c.ALL_TIME_OPTS = [
    (dt, dt.strftime('%I %p %a %d %b'))
    for dt in (
        (c.EPOCH - timedelta(days=c.SETUP_SHIFT_DAYS) + timedelta(hours=i))
        for i in range(c.CON_TOTAL_LENGTH))]
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

c.MAX_BADGE = max(xs[1] for xs in c.BADGE_RANGES.values())

c.JOB_LOCATION_OPTS.sort(key=lambda tup: tup[1])

c.JOB_PAGE_OPTS = (
    ('index',    'Calendar View'),
    ('signups',  'Signups View'),
    ('staffers', 'Staffer Summary')
)
c.WEIGHT_OPTS = (
    ('0.5', 'x0.5'),
    ('1.0', 'x1.0'),
    ('1.5', 'x1.5'),
    ('2.0', 'x2.0'),
    ('2.5', 'x2.5'),
)
c.JOB_DEFAULTS = ['name', 'description', 'duration', 'slots', 'weight', 'visibility', 'required_roles_ids', 'extra15']

c.PREREG_SHIRT_OPTS = sorted(c.PREREG_SHIRT_OPTS if c.PREREG_SHIRT_OPTS else c.SHIRT_OPTS)[1:]
c.MERCH_SHIRT_OPTS = [(c.SIZE_UNKNOWN, 'select a size')] + sorted(list(c.SHIRT_OPTS))
c.DONATION_TIER_OPTS = [(amt, '+ ${}: {}'.format(amt, desc) if amt else desc) for amt, desc in c.DONATION_TIER_OPTS]

c.DONATION_TIER_ITEMS = {}
c.DONATION_TIER_DESCRIPTIONS = _config.get('donation_tier_descriptions', {})
for _ident, _tier in c.DONATION_TIER_DESCRIPTIONS.items():
    [price] = [amt for amt, name in c.DONATION_TIERS.items() if name == _tier['name']]
    _tier['price'] = price
    if price:  # ignore the $0 kickin level
        c.DONATION_TIER_ITEMS[price] = _tier['merch_items'] or _tier['description'].split('|')

c.STORE_ITEM_NAMES = [desc for val, desc in c.STORE_PRICE_OPTS]
c.FEE_ITEM_NAMES = [desc for val, desc in c.FEE_PRICE_OPTS]

c.WRISTBAND_COLORS = defaultdict(lambda: c.WRISTBAND_COLORS[c.DEFAULT_WRISTBAND], c.WRISTBAND_COLORS)

c.SAME_NUMBER_REPEATED = r'^(\d)\1+$'

# Allows 0-9, a-z, A-Z, and a handful of punctuation characters
c.INVALID_BADGE_PRINTED_CHARS = r'[^a-zA-Z0-9!"#$%&\'()*+,\-\./:;<=>?@\[\\\]^_`\{|\}~ "]'
c.EVENT_QR_ID = c.EVENT_QR_ID or c.EVENT_NAME_AND_YEAR.replace(' ', '_').lower()


try:
    _items = sorted([int(step), url] for step, url in _config['volunteer_checklist'].items() if url)
except ValueError:
    log.error('[volunteer_checklist] config options must have integer option names')
    raise
else:
    c.VOLUNTEER_CHECKLIST = [url for step, url in _items]

stripe.api_key = c.STRIPE_SECRET_KEY


# plugins can use this to append paths which will be included as <script> tags, e.g. if a plugin
# appends '../static/foo.js' to this list, that adds <script src="../static/foo.js"></script> to
# all of the pages on the site except for preregistration pages (for performance)
c.JAVASCRIPT_INCLUDES = []


# A list of models that have properties defined for exporting for Guidebook
c.GUIDEBOOK_MODELS = [
    ('GuestGroup_guest', 'Guests'),
    ('GuestGroup_band', 'Bands'),
    ('MITSGame', 'MITS'),
    ('IndieGame', 'MIVS'),
    ('Event_panels', 'Panels'),
    ('Group_dealer', 'Marketplace'),
]


# A list of properties that we will check for when export for Guidebook
# and the column headings Guidebook expects for them
c.GUIDEBOOK_PROPERTIES = [
    ('guidebook_name', 'Name'),
    ('guidebook_subtitle', 'Sub-Title (i.e. Location, Table/Booth, or Title/Sponsorship Level)'),
    ('guidebook_desc', 'Description (Optional)'),
    ('guidebook_location', 'Location/Room'),
    ('guidebook_image', 'Image (Optional)'),
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
c.MITS_APPLICATION_STEPS = 7

# The options for the recommended minimum age for games, as filled out by the teams.
c.MITS_AGE_OPTS = [(i, i) for i in range(4, 20, 2)]


# =============================
# panels
# =============================

c.PANEL_SCHEDULE_LENGTH = int((c.PANELS_ESCHATON - c.PANELS_EPOCH).total_seconds() // 3600) * 2
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
    {'name': 'panel', 'header': 'Panel'},
    {'name': 'mc', 'header': 'MC'},
    {'name': 'bio', 'header': 'Bio Provided'},
    {'name': 'info', 'header': 'Agreement Completed'},
    {'name': 'taxes', 'header': 'W9 Uploaded', 'is_link': True},
    {'name': 'merch', 'header': 'Merch'},
    {'name': 'charity', 'header': 'Charity'},
    {'name': 'badges', 'header': 'Badges Claimed'},
    {'name': 'stage_plot', 'header': 'Stage Plans', 'is_link': True},
    {'name': 'autograph'},
    {'name': 'interview'},
    {'name': 'travel_plans'},
    {'name': 'rehearsal'},
]

# Generate the possible template prefixes per step
for item in c.GUEST_CHECKLIST_ITEMS:
    item['deadline_template'] = ['guest_checklist/', item['name'] + '_deadline.html']
