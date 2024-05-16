import json
import operator
import os
import re
import uuid
import time
import traceback
from collections import defaultdict
from datetime import date, datetime, timedelta
from functools import wraps
from itertools import chain
from uuid import uuid4

import bcrypt
import cherrypy
import six
import sqlalchemy
from dateutil import parser as dateparser
from pockets import cached_classproperty, classproperty, listify
from pockets.autolog import log
from residue import check_constraint_naming_convention, declarative_base, JSON, SessionManager, UTCDateTime, UUID
from sqlalchemy import and_, func, or_
from sqlalchemy.dialects.postgresql.json import JSONB
from sqlalchemy.event import listen
from sqlalchemy.exc import IntegrityError, NoResultFound
from sqlalchemy.orm import Query, joinedload, subqueryload, aliased
from sqlalchemy.orm.attributes import get_history, instance_state
from sqlalchemy.schema import MetaData
from sqlalchemy.types import Boolean, Integer, Float, Date, Numeric
from sqlalchemy.util import immutabledict

import uber
from uber.config import c, create_namespace_uuid
from uber.errors import HTTPRedirect
from uber.decorators import cost_property, department_id_adapter, presave_adjustment, suffix_property
from uber.models.types import Choice, DefaultColumn as Column, MultiChoice
from uber.utils import check_csrf, normalize_email_legacy, create_new_hash, DeptChecklistConf, \
    valid_email, valid_password
from uber.payments import ReceiptManager


def _make_getter(model):
    def getter(
            self, params=None, *, bools=(), checkgroups=(), allowed=(), restricted=False, ignore_csrf=False, **query):

        if query:
            return self.query(model).filter_by(**query).one()
        elif isinstance(params, str):
            return self.query(model).filter_by(id=params).one()
        else:
            if params:
                params = params.copy()
                id = params.pop('id', 'None')
            else:
                id = 'None'
            if id == 'None':
                inst = model()
            else:
                inst = self.query(model).filter_by(id=id).one()

            if not ignore_csrf:
                assert not {k for k in params if k not in allowed} or cherrypy.request.method == 'POST', 'POST required'

            inst.apply(params, bools=bools, checkgroups=checkgroups, restricted=restricted, ignore_csrf=ignore_csrf)

            return inst
    return getter


# Consistent naming conventions are necessary for alembic to be able to
# reliably upgrade and downgrade versions. For more details, see:
# http://alembic.zzzcomputing.com/en/latest/naming.html
naming_convention = {
    'ix': 'ix_%(column_0_label)s',
    'uq': 'uq_%(table_name)s_%(column_0_name)s',
    'fk': 'fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s',
    'pk': 'pk_%(table_name)s'}

if not c.SQLALCHEMY_URL.startswith('sqlite'):
    naming_convention['unnamed_ck'] = check_constraint_naming_convention
    naming_convention['ck'] = 'ck_%(table_name)s_%(unnamed_ck)s',

metadata = MetaData(naming_convention=immutabledict(naming_convention))


@declarative_base(metadata=metadata)
class MagModel:
    id = Column(UUID, primary_key=True, default=lambda: str(uuid4()))

    required = ()
    is_actually_old = False  # Set to true to force preview models to return False for `is_new`

    @cached_classproperty
    def NAMESPACE(cls):
        return create_namespace_uuid(cls.__name__)

    @cached_classproperty
    def _class_attr_names(cls):
        return [
            s for s in dir(cls)
            if s not in ('_class_attrs', '_class_attr_names') and
            not s.startswith('_cached_')]

    @cached_classproperty
    def _class_attrs(cls):
        return {s: getattr(cls, s) for s in cls._class_attr_names}

    def _invoke_adjustment_callbacks(self, label):
        callbacks = []
        for name, attr in self._class_attrs.items():
            if hasattr(attr, '__call__') and hasattr(attr, label):
                callbacks.append(getattr(self, name))
        callbacks.sort(key=lambda f: getattr(f, label))
        for function in callbacks:
            function()

    def presave_adjustments(self):
        self._invoke_adjustment_callbacks('presave_adjustment')

    def predelete_adjustments(self):
        self._invoke_adjustment_callbacks('predelete_adjustment')

    @property
    def email_to_address(self):
        """
        The email address that our automated emails use when emailing this model.
        In some rare cases, a model should have a column named `email` but not always use that in
        automated emails -- override this instead.
        """
        return self.email

    @property
    def gets_emails(self):
        """
        In some cases, we want to apply a global filter to a model that prevents it from
        receiving scheduled emails under certain circumstances. This property allows you
        to define such a filter.
        """
        return True

    @property
    def addons(self):
        """
        This exists only to be overridden by other events; it should return a
        list of strings are the extra things which an attendee or group has
        purchased.  For example, in the MAGStock codebase, we've got code which
        looks something like this::

            @Session.model_mixin
            class Attendee:
                purchased_food = Column(Boolean, default=False)

                @property
                def addons(self):
                    return ['Food'] if self.purchased_food else []

        Our various templates use this information to display a summary to the
        user of what they have purchased, e.g. in the prereg confirmation page
        and in their confirmation emails.
        """
        return []

    @cached_classproperty
    def cost_property_names(cls):
        """Returns the names of all cost properties on this model."""
        return [
            s for s in cls._class_attr_names
            if s not in ['cost_property_names']
            and isinstance(getattr(cls, s), cost_property)]

    @cached_classproperty
    def multichoice_columns(cls):
        return [c for c in cls.__table__.columns if isinstance(c.type, MultiChoice)]

    def auto_update_receipt(self, params):
        """
        Allows event plugins to preprocess a set of params before a model's receipt is updated.
        If we keep the receipt auto-updater around long enough, we should move some of the 
        ReceiptManager class's auto_update_receipt to this function.
        """
        return params

    def calc_default_cost(self):
        """
        Returns the sum of all cost and credit receipt items for this model instance.

        Because things like discounts exist, we ensure default_cost will never
        return a negative value.
        """
        receipt, receipt_items = ReceiptManager.create_new_receipt(self)

        return max(0, sum([(cost * count) for desc, cost, count in receipt_items]) / 100)

    @property
    def stripe_transactions(self):
        """
        Returns all logged Stripe transactions with this model's ID.
        """
        from uber.models.commerce import ReceiptTransaction
        return self.session.query(ReceiptTransaction).filter_by(fk_id=self.id).all()

    @cached_classproperty
    def unrestricted(cls):
        """
        Returns a set of column names which are allowed to be set by non-admin
        attendees filling out one of the registration forms.
        """
        return {col.name for col in cls.__table__.columns if not getattr(col, 'admin_only', True)}

    @cached_classproperty
    def all_bools(cls):
        """Returns the set of Boolean column names for this table."""
        return {col.name for col in cls.__table__.columns if isinstance(col.type, Boolean)}

    @cached_classproperty
    def all_checkgroups(cls):
        """Returns the set of MultiChoice column names for this table."""
        return {col.name for col in cls.__table__.columns if isinstance(col.type, MultiChoice)}

    @cached_classproperty
    def regform_bools(cls):
        """Returns the set of non-admin-only Boolean columns for this table."""
        return {colname for colname in cls.all_bools if colname in cls.unrestricted}

    @cached_classproperty
    def regform_checkgroups(cls):
        """
        Returns the set of non-admin-only MultiChoice columns for this table.
        """
        return {colname for colname in cls.all_checkgroups if colname in cls.unrestricted}

    @cached_classproperty
    def import_fields(cls):
        """
        Allows event plugins to inject extra import fields for the API export.
        """
        return []

    @classproperty
    def _extra_apply_attrs(cls):
        """
        Returns a set of extra attrs used by apply(). These are settable
        attributes or properties that are not in cls.__table__columns.
        """
        return set()

    @classproperty
    def _extra_apply_attrs_restricted(cls):
        """
        Returns a set of extra attrs used by apply(restricted=True). These are
        settable attributes or properties that are not in cls.__table__columns.
        """
        return set()

    def _get_relation_ids(self, relation):
        return getattr(self, '_relation_ids', {}).get(relation, (None, None))

    def _set_relation_ids(self, relation, ModelClass, ids):
        _relation_ids = getattr(self, '_relation_ids', {})
        _relation_ids[relation] = (ModelClass, ids)
        setattr(self, '_relation_ids', _relation_ids)

    @presave_adjustment
    def _convert_relation_ids_to_instances(self):
        _relation_ids = getattr(self, '_relation_ids', {})
        for relation, (ModelClass, ids) in _relation_ids.items():
            self.session.set_relation_ids(self, relation, ModelClass, ids)
        setattr(self, '_relation_ids', {})

    @property
    def session(self):
        """
        Returns the session object which this model instance is attached to,
        or None if this instance is not attached to a session.
        """
        return Session.session_factory.object_session(self)

    @classmethod
    def get_field(cls, name):
        """Returns the column object with the provided name for this model."""
        return cls.__table__.columns[name]

    def __eq__(self, m):
        return self.id is not None and isinstance(m, MagModel) and self.id == m.id

    def __ne__(self, m):
        return not (self == m)

    def __hash__(self):
        return hash(self.id)

    @property
    def is_new(self):
        """
        Boolean property indicating whether or not this instance has already
        been saved to the database or if it's a new instance which has never
        been saved and thus has no corresponding row in its database table.
        """
        if self.is_actually_old:
            return False
        return not instance_state(self).persistent

    @property
    def created(self):
        return self.get_tracking_by_instance(self, action=c.CREATED, last_only=True)

    @property
    def last_updated(self):
        return self.get_tracking_by_instance(self, action=c.UPDATED, last_only=True)

    @property
    def db_id(self):
        """
        A common convention in our forms is to pass an "id" parameter of "None"
        for new objects and to pass the actual id for objects which already
        exist in our database, which lets the backend know whether to perform a
        save or an update.  This method returns "None" for new objects and the
        id for existing objects, for use in such forms.
        """
        return None if self.is_new else self.id

    def orig_value_of(self, name):
        """
        Sometimes we mutate a model instance but then want to get the original
        value of a column before we changed it before we perform a save.  This
        method returns the original value (i.e. the value currently in the db)
        for the column whose name is provided.  If the value has not changed,
        this just returns the current value of that field.
        """
        hist = get_history(self, name)
        return (hist.deleted or hist.unchanged or [getattr(self, name)])[0]

    @suffix_property
    def _ints(self, name, val):
        """
        Given a column that uses a tuple of integers and strings, returns a
        list of integers. This allows us to use 'x in y' searching for
        MultiChoice columns.

        These arguments are supplied by the @suffix_property decorator based
        on the variable name preceding '_ints'.

        Args:
            name: The name of the column we're inspecting, e.g., "interests".
            val: The list of tuples the column uses as possible values,
                e.g., "c.INTEREST_OPTS".

        Returns:
            A list of integers or an empty list if val is falsey.

        """
        if not val or not name:
            return []

        choices = dict(self.get_field(name).type.choices)
        val = self.get_field(name).type.convert_if_labels(val)
        return [int(i) for i in str(val).split(',') if i and int(i) in choices]

    @suffix_property
    def _label(self, name, val):
        if not val or not name:
            return ''

        try:
            val = int(val)
        except ValueError:
            log.debug('{} is not an int. Did we forget to migrate data for {} during a DB migration?'.format(val, name))
            return ''

        if val == -1:
            return "Unknown"

        label = self.get_field(name).type.choices.get(val)
        if not label:
            log.debug('{} does not have a label for {}, check your enum generating code'.format(name, val))
            return ''
        return label

    @suffix_property
    def _local(self, name, val):
        return val.astimezone(c.EVENT_TIMEZONE)

    @suffix_property
    def _labels(self, name, val):
        ints = getattr(self, name + '_ints')
        labels = dict(self.get_field(name).type.choices)
        return sorted(labels[i] for i in ints)

    def __getattr__(self, name):
        suffixed = suffix_property.check(self, name)
        if suffixed is not None:
            return suffixed

        choice = getattr(c, name, None)
        if choice is not None:
            if len(self.multichoice_columns) == 1:
                multi = self.multichoice_columns[0]
                if choice in multi.type.choices_dict:
                    return choice in getattr(self, multi.name + '_ints')

        if name.startswith('is_'):
            return self.__class__.__name__.lower() == name[3:]

        if name.startswith('default_') and name.endswith('_cost'):
            if self.active_receipt:
                log.debug('Cost property {} was called for object {}, \
                          which has an active receipt. This may cause problems.'.format(name, self))

        receipt_items = uber.receipt_items.cost_calculation.items
        try:
            cost_calc = receipt_items[self.__class__.__name__][name[8:]](self)
            if not cost_calc:
                return 0

            try:
                return sum(item[0] * item[1] for item in cost_calc[1].items()) / 100
            except AttributeError:
                if len(cost_calc) > 3:
                    return cost_calc[1] * cost_calc[3] / 100
                else:
                    return cost_calc[1] / 100
        except Exception:
            pass

        raise AttributeError(self.__class__.__name__ + '.' + name)

    def get_tracking_by_instance(self, instance, action, last_only=True):
        from uber.models.tracking import Tracking
        query = self.session.query(Tracking).filter_by(fk_id=instance.id, action=action).order_by(Tracking.when.desc())
        return query.first() if last_only else query.all()

    def coerce_column_data(self, column, value):
        if isinstance(value, six.string_types):
            value = value.strip()

        try:
            if value is None:
                return  # Totally fine for value to be None

            elif value == '' and isinstance(column.type, (UUID, Float, Numeric, Choice, Integer, UTCDateTime, Date)):
                return None

            elif isinstance(column.type, Boolean):
                if isinstance(value, six.string_types):
                    return value.strip().lower() not in ('f', 'false', 'n', 'no', '0')
                return bool(value)

            elif isinstance(column.type, Float):
                return float(value)

            elif isinstance(column.type, Numeric):
                if isinstance(value, six.string_types) and value.endswith('.0'):
                    return int(value[:-2])
                else:
                    return int(float(value))

            elif isinstance(column.type, (MultiChoice)):
                if isinstance(value, list):
                    value = ','.join(map(lambda x: str(x).strip(), value))
                else:
                    value = str(value).strip()
                return column.type.convert_if_labels(value)

            elif isinstance(column.type, Choice):
                return column.type.convert_if_label(value)

            elif isinstance(column.type, Integer):
                value = int(float(value))

            elif isinstance(column.type, UTCDateTime):
                try:
                    value = datetime.strptime(value, c.TIMESTAMP_FORMAT)
                except ValueError:
                    value = dateparser.parse(value)

                if not value.tzinfo:
                    return c.EVENT_TIMEZONE.localize(value)
                else:
                    return value

            elif isinstance(column.type, Date):
                try:
                    value = datetime.strptime(value, c.DATE_FORMAT)
                except ValueError:
                    value = dateparser.parse(value)
                return value.date()

            elif isinstance(column.type, JSONB) and isinstance(value, str):
                return json.loads(value)

        except Exception as error:
            log.debug(
                'Ignoring error coercing value for column {}.{}: {}', self.__tablename__, column.name, error)
        return value

    def apply(self, params, *, bools=(), checkgroups=(), restricted=True, ignore_csrf=True):
        """
        Args:
            restricted (bool): If True, restrict any changes only to fields
                which we allow attendees to set on their own. If False, allow
                changes to any fields.
        """
        bools = self.regform_bools if restricted else bools
        checkgroups = self.regform_checkgroups if restricted else checkgroups
        for column in self.__table__.columns:
            if (not restricted or column.name in self.unrestricted) and column.name in params and column.name != 'id':
                value = params[column.name]
                setattr(self, column.name, self.coerce_column_data(column, value))

        for column in self.__table__.columns:
            if (not restricted or column.name in self.unrestricted) \
                    and (column.type is JSON or isinstance(column.type, JSON)):

                fields = getattr(self, '_{}_fields'.format(column.name), {})
                for field in fields.keys():
                    if field in params:
                        setattr(self, field, params[field])

        if cherrypy.request.method.upper() == 'POST':
            for column in self.__table__.columns:
                if column.name in bools:
                    setattr(self, column.name, bool(int(params.get(column.name, 0))))
                elif column.name in checkgroups and column.name not in params:
                    setattr(self, column.name, '')

            if not ignore_csrf:
                check_csrf(params.get('csrf_token'))

        _extra_apply_attrs = self._extra_apply_attrs_restricted if restricted else self._extra_apply_attrs

        for attr in _extra_apply_attrs:
            if attr in params:
                setattr(self, attr, params[attr])

        return self

    def timespan(self, minute_increment=1):
        def minutestr(dt):
            return '' if dt.minute == 0 else dt.strftime(':%M')

        timespan = timedelta(minutes=minute_increment * self.duration)
        endtime = self.start_time_local + timespan

        startstr = self.start_time_local.strftime('%I').lstrip('0') + minutestr(self.start_time_local)
        endstr = endtime.strftime('%I').lstrip('0') + minutestr(endtime) + endtime.strftime('%p').lower()

        if self.start_time_local.day == endtime.day:
            endstr += endtime.strftime(' %A')
            if self.start_time_local.hour < 12 and endtime.hour >= 12:
                return startstr + 'am - ' + endstr
            else:
                return startstr + '-' + endstr
        else:
            return startstr + self.start_time_local.strftime('pm %a - ') + endstr + endtime.strftime(' %a')


# Make all of our model classes available from uber.models
from uber.models.admin import *  # noqa: F401,E402,F403
from uber.models.promo_code import *  # noqa: F401,E402,F403
from uber.models.attendee import *  # noqa: F401,E402,F403
from uber.models.badge_printing import *  # noqa: F401,E402,F403
from uber.models.commerce import *  # noqa: F401,E402,F403
from uber.models.department import *  # noqa: F401,E402,F403
from uber.models.email import *  # noqa: F401,E402,F403
from uber.models.group import *  # noqa: F401,E402,F403
from uber.models.legal import *  # noqa: F401,E402,F403
from uber.models.tracking import *  # noqa: F401,E402,F403
from uber.models.types import *  # noqa: F401,E402,F403
from uber.models.api import *  # noqa: F401,E402,F403
from uber.models.hotel import *  # noqa: F401,E402,F403
from uber.models.attendee_tournaments import *  # noqa: F401,E402,F403
from uber.models.marketplace import *  # noqa: F401,E402,F403
from uber.models.mivs import *  # noqa: F401,E402,F403
from uber.models.mits import *  # noqa: F401,E402,F403
from uber.models.panels import *  # noqa: F401,E402,F403
from uber.models.attraction import *  # noqa: F401,E402,F403
from uber.models.tabletop import *  # noqa: F401,E402,F403
from uber.models.guests import *  # noqa: F401,E402,F403
from uber.models.art_show import *  # noqa: F401,E402,F403

# Explicitly import models used by the Session class to quiet flake8
from uber.models.admin import AccessGroup, AdminAccount, WatchList, WorkstationAssignment  # noqa: E402
from uber.models.art_show import ArtShowApplication, ArtShowBidder  # noqa: E402
from uber.models.attendee import Attendee, AttendeeAccount  # noqa: E402
from uber.models.badge_printing import PrintJob  # noqa: E402
from uber.models.commerce import ModelReceipt  # noqa: E402
from uber.models.department import Job, Shift, Department, DeptRole  # noqa: E402
from uber.models.email import Email  # noqa: E402
from uber.models.group import Group  # noqa: E402
from uber.models.guests import GuestGroup  # noqa: E402
from uber.models.hotel import LotteryApplication
from uber.models.mits import MITSApplicant, MITSTeam  # noqa: E402
from uber.models.mivs import IndieJudge, IndieGame, IndieStudio  # noqa: E402
from uber.models.panels import PanelApplication, PanelApplicant  # noqa: E402
from uber.models.promo_code import PromoCode, PromoCodeGroup  # noqa: E402
from uber.models.tracking import Tracking  # noqa: E402


class Session(SessionManager):
    # This looks strange, but `sqlalchemy.create_engine` will throw an error
    # if it's passed arguments that aren't supported by the given DB engine.
    # For example, SQLite doesn't support either `pool_size` or `max_overflow`,
    # so if `sqlalchemy_pool_size` or `sqlalchemy_max_overflow` are set with
    # a value of -1, they are not added to the keyword args.
    _engine_kwargs = dict((k, v) for (k, v) in [
        ('pool_size', c.SQLALCHEMY_POOL_SIZE),
        ('max_overflow', c.SQLALCHEMY_MAX_OVERFLOW),
        ('pool_pre_ping', True),
        ('pool_recycle', c.SQLALCHEMY_POOL_RECYCLE)] if v > -1)
    engine = sqlalchemy.create_engine(c.SQLALCHEMY_URL, **_engine_kwargs)

    @classmethod
    def initialize_db(cls, modify_tables=False, drop=False, initialize=False):
        """
        Initialize the database and optionally create/drop tables.

        Initializes the database connection for use, and attempt to create any
        tables registered in our metadata which do not actually exist yet in
        the database.

        This calls the underlying ubersystem function, HOWEVER, in order to
        actually create any tables, you must specify modify_tables=True.  The
        reason is, we need to wait for all models from all plugins to insert
        their mixin data, so we wait until one spot in order to create the
        database tables.

        Any calls to initialize_db() that do not specify modify_tables=True or
        drop=True are ignored.

        i.e. anywhere in ubersystem that calls initialize_db() will be ignored.
        i.e. ubersystem is forcing all calls that don't specify
        modify_tables=True or drop=True to be ignored.

        Calling initialize_db with modify_tables=False and drop=True will leave
        you with an empty database.

        Keyword Arguments:
            modify_tables: If False, this function will not attempt to create
                any database objects (tables, columns, constraints, etc...)
                Defaults to False.
            drop: USE WITH CAUTION: If True, then we will drop any tables in
                the database. Defaults to False.
        """
        for model in cls.all_models():
            if not hasattr(cls.SessionMixin, model.__tablename__):
                setattr(cls.SessionMixin, model.__tablename__, _make_getter(model))

        if drop or modify_tables or initialize:
            super(Session, cls).initialize_db(drop=drop, create=modify_tables)
            if drop:
                from uber.migration import stamp
                stamp('heads' if modify_tables else None)

    class QuerySubclass(Query):
        @property
        def is_single_table_query(self):
            return len(self.column_descriptions) == 1

        @property
        def model(self):
            assert self.is_single_table_query, \
                'actions such as .order() and .icontains() and .iexact() are only valid for single-table queries'

            return self.column_descriptions[0]['type']

        def order(self, attrs):
            order = []
            for attr in listify(attrs):
                col = getattr(self.model, attr.lstrip('-'))
                order.append(col.desc() if attr.startswith('-') else col)
            return self.order_by(*order)

        def icontains_condition(self, attr=None, val=None, **filters):
            """
            Take column names and values, and build a condition/expression
            that is true when all named columns contain the corresponding
            values, case-insensitive.

            This operation is very similar to the "contains" method in
            SQLAlchemy, but case insensitive - i.e. it uses "ilike" instead
            of "like".

            Note that an "and" is used: all columns must match, not just one.
            More complex conditions can be built by using or_/etc on the result
            of this method.
            """
            conditions = []
            if len(self.column_descriptions) == 1 and filters:
                for colname, val in filters.items():
                    conditions.append(getattr(self.model, colname).ilike('%{}%'.format(val)))
            if attr and val:
                conditions.append(attr.ilike('%{}%'.format(val)))
            return and_(*conditions)

        def icontains(self, attr=None, val=None, **filters):
            """
            Take the names of columns and values, and filters the query to
            items where each named columns contain the values,
            case-insensitive.

            This operation is very similar to calling
            query.filter(contains(...)), but works with a case-insensitive
            "contains".

            Note that an "and" is used: all columns must match, not just one.
            """
            condition = self.icontains_condition(attr=attr, val=val, **filters)
            return self.filter(condition)

        def iexact(self, **filters):
            filters = [func.lower(getattr(self.model, attr)) == func.lower(val) for attr, val in filters.items()]
            return self.filter(*filters)

    class SessionMixin:
        def current_admin_account(self):
            if getattr(cherrypy, 'session', {}).get('account_id'):
                return self.admin_account(cherrypy.session.get('account_id'))

        def admin_attendee(self):
            if getattr(cherrypy, 'session', {}).get('account_id'):
                try:
                    return self.admin_account(cherrypy.session.get('account_id')).attendee
                except NoResultFound:
                    return

        def current_attendee_account(self):
            if c.ATTENDEE_ACCOUNTS_ENABLED and getattr(cherrypy, 'session', {}).get('attendee_account_id'):
                try:
                    return self.attendee_account(cherrypy.session.get('attendee_account_id'))
                except sqlalchemy.orm.exc.NoResultFound:
                    cherrypy.session['attendee_account_id'] = ''

        def get_attendee_account_by_attendee(self, attendee):
            logged_in_account = self.current_attendee_account()
            if not logged_in_account:
                return

            attendee_accounts = attendee.managers
            if logged_in_account in attendee_accounts:
                return logged_in_account
            elif len(attendee.managers) == 1:
                return attendee.managers[0]

        def logged_in_volunteer(self):
            return self.attendee(cherrypy.session.get('staffer_id'))

        def admin_has_staffer_access(self, staffer, access="view"):
            admin = self.current_admin_account()
            if admin.full_shifts_admin:
                return True

            dept_ids_with_inherent_role = [dept_m.department_id for dept_m in
                                           admin.attendee.dept_memberships_with_inherent_role]
            return set(staffer.assigned_depts_ids).intersection(dept_ids_with_inherent_role)

        def admin_can_see_guest_group(self, guest):
            return guest.group_type_label.upper().replace(' ', '_') \
                in self.current_admin_account().viewable_guest_group_types

        def admin_attendee_max_access(self, attendee, read_only=True):
            admin = self.current_admin_account()
            if not admin:
                return 0

            if admin.full_registration_admin or attendee.creator == admin.attendee or \
                    attendee == admin.attendee or attendee.is_new:
                return AccessGroup.FULL

            if attendee.access_sections:
                return max([admin.max_level_access(section,
                                                   read_only=read_only) for section in attendee.access_sections])

        def admin_can_create_attendee(self, attendee):
            admin = self.current_admin_account()
            if not admin:
                return

            if admin.full_registration_admin:
                return True

            return admin.full_shifts_admin if attendee.badge_type == c.STAFF_BADGE else \
                self.admin_attendee_max_access(attendee) >= AccessGroup.DEPT

        def viewable_groups(self):
            from uber.models import Group, GuestGroup
            admin = self.current_admin_account()

            if admin.full_registration_admin:
                return self.query(Group)

            subqueries = [self.query(Group).filter(Group.creator == admin.attendee)]

            group_id = admin.attendee.group.id if admin.attendee.group else ''
            if group_id:
                subqueries.append(self.query(Group).filter(Group.id == group_id))

            for key, val in c.GROUP_TYPE_OPTS:
                if val.lower() + '_admin' in admin.read_or_write_access_set:
                    subqueries.append(
                        self.query(Group).join(
                            GuestGroup, Group.id == GuestGroup.group_id).filter(GuestGroup.group_type == key
                                                                                )
                    )

            if 'dealer_admin' in admin.read_or_write_access_set:
                subqueries.append(
                    self.query(Group).filter(Group.is_dealer)
                )

            return subqueries[0].union(*subqueries[1:])

        def access_query_matrix(self):
            """
            There's a few different situations where we want to add certain subqueries to find attendees
            based on different site sections. This matrix returns queries keyed by site section.
            """
            admin = self.current_admin_account()
            return_dict = {'created': self.query(Attendee).filter(
                or_(Attendee.creator == admin.attendee, Attendee.id == admin.attendee.id))}
            # Guest groups
            for group_type, badge_and_ribbon_filter in [(c.BAND,
                                                         and_(Attendee.badge_type == c.GUEST_BADGE,
                                                              Attendee.ribbon.contains(c.BAND))),
                                                        (c.GUEST,
                                                         and_(Attendee.badge_type == c.GUEST_BADGE,
                                                              ~Attendee.ribbon.contains(c.BAND)))]:
                return_dict[c.GROUP_TYPES[group_type].lower() + '_admin'] = (
                    self.query(Attendee).join(Group, Attendee.group_id == Group.id)
                        .join(GuestGroup, Group.id == GuestGroup.group_id).filter(
                            or_(
                                or_(
                                    badge_and_ribbon_filter,
                                    and_(
                                        Group.id == Attendee.group_id,
                                        GuestGroup.group_id == Group.id,
                                        GuestGroup.group_type == group_type,
                                        )
                                )
                            )
                        )
                )

            return_dict['panels_admin'] = self.query(Attendee).outerjoin(PanelApplicant).filter(
                                                 or_(Attendee.ribbon.contains(c.PANELIST_RIBBON),
                                                     Attendee.panel_applications != None,  # noqa: E711
                                                     Attendee.assigned_panelists != None,  # noqa: E711
                                                     Attendee.panel_applicants != None,  # noqa: E711
                                                     Attendee.panel_feedback != None))  # noqa: E711
            return_dict['dealer_admin'] = self.query(Attendee).join(Group,
                                                                    Attendee.group_id == Group.id
                                                                    ).filter(Attendee.is_dealer)
            return_dict['mits_admin'] = self.query(Attendee).join(MITSApplicant).filter(Attendee.mits_applicants)
            return_dict['mivs_admin'] = (self.query(Attendee).join(Group, Attendee.group_id == Group.id)
                                         .join(GuestGroup, Group.id == GuestGroup.group_id).filter(
                                             and_(Group.id == Attendee.group_id,
                                                  GuestGroup.group_id == Group.id, GuestGroup.group_type == c.MIVS)
                                                  ))
            return_dict['art_show_admin'] = self.query(Attendee
                                                       ).outerjoin(
                                                           ArtShowApplication,
                                                           or_(ArtShowApplication.attendee_id == Attendee.id,
                                                               ArtShowApplication.agent_id == Attendee.id)
                                                        ).outerjoin(ArtShowBidder).filter(
                                                            or_(Attendee.art_show_bidder != None,  # noqa: E711
                                                                Attendee.art_show_purchases != None,  # noqa: E711
                                                                Attendee.art_show_applications != None,  # noqa: E711
                                                                Attendee.art_agent_applications != None)  # noqa: E711
                                                        )
            return return_dict

        def viewable_attendees(self):
            from uber.models import Attendee
            admin = self.current_admin_account()

            if admin.full_registration_admin:
                return self.query(Attendee)

            subqueries = [self.access_query_matrix()['created']]

            for key, val in self.access_query_matrix().items():
                if key in admin.read_or_write_access_set:
                    subqueries.append(val)

            if admin.full_shifts_admin:
                subqueries.append(
                    self.query(Attendee).filter(Attendee.staffing)
                )

            return subqueries[0].union(*subqueries[1:])

        def checklist_status(self, slug, department_id):
            attendee = self.admin_attendee()
            conf = DeptChecklistConf.instances.get(slug)
            if not conf:
                raise ValueError(
                    "Can't access dept checklist INI settings for section '{}', check your INI file".format(slug))

            if not department_id:
                return {'conf': conf, 'relevant': False, 'completed': None}

            department = self.query(Department).get(department_id)
            if department:
                return {
                    'conf': conf,
                    'relevant': attendee.can_admin_checklist_for(department),
                    'completed': department.checklist_item_for_slug(conf.slug)
                }
            else:
                return {
                    'conf': conf,
                    'relevant': attendee.can_admin_checklist,
                    'completed': attendee.checklist_item_for_slug(conf.slug)
                }

        def jobs_for_signups(self, all=False):
            fields = [
                'name', 'department_id', 'department_name', 'description',
                'weight', 'start_time_local', 'end_time_local', 'duration',
                'weighted_hours', 'restricted', 'extra15', 'taken',
                'visibility', 'is_public', 'is_setup', 'is_teardown']
            jobs = self.logged_in_volunteer().possible_and_current
            restricted_minutes = set()
            for job in jobs:
                if job.required_roles:
                    restricted_minutes.add(frozenset(job.minutes))
            if all:
                return [job.to_dict(fields) for job in jobs]
            return [
                job.to_dict(fields)
                for job in jobs if (job.required_roles or frozenset(job.minutes) not in restricted_minutes)]

        def possible_match_list(self):
            possibles = defaultdict(list)
            for a in self.valid_attendees():
                possibles[a.email.lower()].append(a)
                possibles[a.first_name, a.last_name].append(a)
            return possibles

        def guess_attendee_watchentry(self, attendee, active=True):
            """
            Finds all watchlist entries that match a given attendee.
            Only active entries are matched. Watchlist entries with confirmed attendees
            are still matched to attendees -- otherwise attendees could dodge bans just by
            registering twice.

            A watchlist entry is considered a match if both of the following are true:
                a) one of the entry's first names or its last name matches the attendee's
                b) the entry's email address or date of birth matches the attendee's

            Because this could be run while in the middle of creating an attendee, we
            need to do several checks on how the attendee's DOB might be formatted.
            """
            or_clauses = [
                and_(
                    WatchList.email != '',
                    func.lower(WatchList.email) == attendee.email.lower())]

            if attendee.birthdate:
                if isinstance(attendee.birthdate, six.string_types):
                    try:
                        birthdate = dateparser.parse(attendee.birthdate).date()
                    except Exception:
                        log.debug('Error parsing attendee birthdate: {}'.format(attendee.birthdate))
                    else:
                        or_clauses.append(WatchList.birthdate == birthdate)
                elif isinstance(attendee.birthdate, datetime):
                    or_clauses.append(WatchList.birthdate == attendee.birthdate.date())
                elif isinstance(attendee.birthdate, date):
                    or_clauses.append(WatchList.birthdate == attendee.birthdate)

            return self.query(WatchList).filter(and_(
                or_(func.lower(WatchList.first_names).contains(attendee.first_name.lower()),
                    func.lower(WatchList.last_name) == attendee.last_name.lower()),
                or_(*or_clauses),
                WatchList.active == active)).all()  # noqa: E712

        def guess_watchentry_attendees(self, entry):
            return self.query(Attendee).filter(
                or_(func.lower(Attendee.first_name).in_(entry.first_name_list),
                    func.lower(Attendee.last_name) == entry.last_name.lower()),
                or_(and_(
                        Attendee.email != '',
                        func.lower(Attendee.email) == entry.email.lower()
                        ),
                    and_(
                        Attendee.birthdate != None,  # noqa: E711
                        Attendee.birthdate == entry.birthdate
                        ),
                    ),
                Attendee.watchlist_id == None).all()  # noqa: E711

        def get_attendee_account_by_email(self, email):
            return self.query(AttendeeAccount).filter_by(normalized_email=normalize_email_legacy(email)).one()

        def get_admin_account_by_email(self, email):
            from uber.utils import normalize_email_legacy
            return self.query(AdminAccount
                              ).join(Attendee).filter(Attendee.normalized_email == normalize_email_legacy(email)).one()

        def no_email(self, subject):
            return not self.query(Email).filter_by(subject=subject).all()

        def lookup_attendee(self, first_name, last_name, email, zip_code):
            attendees = self.query(Attendee).iexact(
                first_name=first_name,
                last_name=last_name,
                zip_code=zip_code
            ).filter(
                Attendee.normalized_email == normalize_email_legacy(email),
                Attendee.is_valid == True  # noqa: E712
            ).limit(10).all()

            if attendees:
                statuses = defaultdict(lambda: six.MAXSIZE, {
                    c.COMPLETED_STATUS: 0,
                    c.NEW_STATUS: 1,
                    c.REFUNDED_STATUS: 2,
                    c.DEFERRED_STATUS: 3,
                    c.WATCHED_STATUS: 4,
                    c.UNAPPROVED_DEALER_STATUS: 5,
                    c.NOT_ATTENDING: 6})

                attendees = sorted(
                    attendees, key=lambda a: statuses[a.badge_status])
                return attendees[0]

            raise ValueError('Attendee not found')

        def create_or_find_attendee_by_id(self, **params):
            message = ''
            if params.get('attendee_id', ''):
                try:
                    attendee = self.attendee(id=params['attendee_id'])
                except Exception:
                    try:
                        attendee = self.attendee(public_id=params['attendee_id'])
                    except Exception:
                        return \
                            None, \
                            'The confirmation number you entered is not valid, ' \
                            'or there is no matching badge.'

                if not attendee.is_valid:
                    return None, \
                           'This badge is invalid. Please contact registration.'
            else:
                attendee_params = {
                    attr: params.get(attr, '')
                    for attr in ['first_name', 'last_name', 'email']}
                attendee = self.attendee(attendee_params, restricted=True,
                                         ignore_csrf=True)
                attendee.placeholder = True
                if not params.get('email', ''):
                    message = 'Email address is a required field.'
                elif c.ATTENDEE_ACCOUNTS_ENABLED:
                    if self.current_attendee_account():
                        self.add_attendee_to_account(attendee, self.current_attendee_account())
                    else:
                        password = params.get('account_password')
                        if password and password != params.get('confirm_password'):
                            message = 'Password confirmation does not match.'
                        else:
                            message = valid_password(password) or valid_email(params.get('email', ''))
                        if not message:
                            new_account = self.create_attendee_account(params.get('email', ''), password=password)
                            self.add_attendee_to_account(attendee, new_account)
                            cherrypy.session['attendee_account_id'] = new_account.id
            return attendee, message

        def create_admin_account(self, attendee, password='', generate_pwd=True, **params):
            from uber.utils import genpasswd

            if not password and generate_pwd:
                password = genpasswd()

            new_account = AdminAccount(
                attendee=attendee,
                hashed=create_new_hash(password))
            if 'judge' in params:
                new_account.judge = params.pop('judge')
            new_account.apply(params)
            self.add(new_account)
            return new_account, password

        def create_attendee_account(self, email=None, password=None):
            from uber.models import AttendeeAccount
            from uber.utils import normalize_email

            new_account = AttendeeAccount(
                email=normalize_email(email),
                hashed=create_new_hash(password) if password else '')
            self.add(new_account)

            return new_account

        def add_attendee_to_account(self, attendee, account):
            unclaimed_account = account.hashed != '' and not account.is_sso_account

            if c.ONE_MANAGER_PER_BADGE and attendee.managers and not unclaimed_account:
                attendee.managers.clear()
            if attendee not in account.attendees:
                account.attendees.append(attendee)

        def match_attendee_to_account(self, attendee):
            existing_account = self.query(AttendeeAccount
                                          ).filter_by(normalized_email=normalize_email_legacy(attendee.email)).first()
            if existing_account:
                self.add_attendee_to_account(attendee, existing_account)

        def get_assigned_terminal_id(self):
            reg_station_id = cherrypy.session.get('reg_station', '')

            if not reg_station_id:
                return "Workstation ID not set!", None

            workstation_assignment = self.query(WorkstationAssignment
                                                ).filter_by(reg_station_id=int(reg_station_id)).first()

            if not workstation_assignment:
                return "This workstation does not have anything assigned, \
                    please double-check your workstation number.", None

            if not workstation_assignment.terminal_id:
                return "This workstation has no terminal assigned, please contact a manager.", None

            lookup_key = workstation_assignment.terminal_id.lower().replace('-', '')
            if lookup_key not in c.TERMINAL_ID_TABLE:
                return f"Could not find terminal ID {workstation_assignment.terminal_id} in our terminal lookup table."

            return "", c.TERMINAL_ID_TABLE[lookup_key]

        def get_receipt_by_model(self, model, include_closed=False, create_if_none=""):
            receipt_select = self.query(ModelReceipt).filter_by(owner_id=model.id, owner_model=model.__class__.__name__)
            if not include_closed:
                receipt_select = receipt_select.filter(ModelReceipt.closed == None)  # noqa: E711
            receipt = receipt_select.first()

            if not receipt and create_if_none:
                receipt, receipt_items = ReceiptManager.create_new_receipt(model, create_model=True)

                self.add(receipt)
                if create_if_none != "BLANK":
                    self.add_all(receipt_items)
                self.commit()
            return receipt

        def get_model_by_receipt(self, receipt):
            cls = getattr(uber.models, receipt.owner_model)
            if cls:
                return self.query(cls).filter_by(id=receipt.owner_id).first()

        def update_paid_from_receipt(self, attendee, receipt):
            if receipt.item_total == 0 and attendee.paid in [c.PENDING, c.NOT_PAID]:
                if attendee.paid == c.PENDING and attendee.badge_status == c.PENDING_STATUS:
                    attendee.badge_status = c.NEW_STATUS
                attendee.paid = c.NEED_NOT_PAY
            elif receipt.current_amount_owed > 0 and attendee.paid == c.NEED_NOT_PAY:
                attendee.paid = c.NOT_PAID
            return attendee

        def refresh_receipt_and_model(self, model, is_prereg=False):
            receipt = self.get_receipt_by_model(model)
            if receipt:
                for txn in receipt.pending_txns:
                    txn.check_paid_from_stripe()
                self.refresh(receipt)

            if isinstance(model, Group):
                model.cost = model.calc_default_cost()
            else:
                model.default_cost = model.calc_default_cost()

            if isinstance(model, Attendee) and receipt and not is_prereg:
                self.update_paid_from_receipt(model, receipt)
                self.merge(model)

            try:
                self.refresh(model)
            except sqlalchemy.exc.InvalidRequestError:
                # Non-persistent object, so nothing to refresh
                pass

            return receipt

        def get_terminal_settlements(self):
            from uber.models import TerminalSettlement

            settlements = {}

            counts_base_query = self.query(TerminalSettlement.batch_timestamp,
                                           func.count(TerminalSettlement.batch_timestamp))

            settlements['completed'] = counts_base_query.filter(or_(TerminalSettlement.error != '',
                                                                    TerminalSettlement.response != {})).group_by(
                                                                        TerminalSettlement.batch_timestamp).order_by(
                                                                        TerminalSettlement.batch_timestamp
                                                                        ).all()

            settlements['succeeded'] = dict(counts_base_query.filter(TerminalSettlement.error == '',
                                                                     TerminalSettlement.response != {}).group_by(
                                                                         TerminalSettlement.batch_timestamp).all())

            settlements['in_progress'] = self.query(TerminalSettlement.batch_timestamp,
                                                    TerminalSettlement.batch_who,
                                                    TerminalSettlement.workstation_num,
                                                    TerminalSettlement.terminal_id
                                                    ).filter(TerminalSettlement.error == '',
                                                             TerminalSettlement.response == {}).all()

            settlements['errors'] = {}
            settlements['batch_info'] = dict(self.query(TerminalSettlement.batch_timestamp,
                                                        TerminalSettlement.batch_who).distinct().all())

            for timestamp, who in settlements['batch_info'].items():
                settlements['errors'][timestamp] = self.query(TerminalSettlement.workstation_num,
                                                              TerminalSettlement.terminal_id,
                                                              TerminalSettlement.error).filter(
                                                                  TerminalSettlement.batch_timestamp == timestamp,
                                                                  TerminalSettlement.error != '').all()

            return settlements

        def attendee_from_marketplace_app(self, **params):
            attendee, message = self.create_or_find_attendee_by_id(**params)
            if message:
                return attendee, message
            elif attendee.marketplace_applications:
                return attendee, \
                       'There is already a marketplace application ' \
                       'for that badge!'

            return attendee, message

        def attendee_from_art_show_app(self, **params):
            attendee, message = self.create_or_find_attendee_by_id(**params)
            if message:
                return attendee, message
            elif attendee.art_show_applications:
                return attendee, \
                    'There is already an art show application ' \
                    'for that badge!'

            if params.get('not_attending', ''):
                attendee.badge_status = c.NOT_ATTENDING

            return attendee, ''

        def lookup_agent_code(self, code):
            return self.query(ArtShowApplication).filter_by(agent_code=code).all()

        def add_promo_code_to_attendee(self, attendee, code, used_codes=defaultdict(int)):
            """
            Convenience method for adding a promo code to an attendee.

            This method sets both the `promo_code` and `promo_code_id`
            properties of `attendee`. Due to the way the `Attendee.promo_code`
            relationship is defined, the `Attendee.promo_code_id` isn't
            automatically set, which makes this method a nice way of setting
            both.

            Arguments:
                attendee (Attendee): The Attendee for which the promo code
                    should be added.
                code (str): The promo code as typed by an end user, or an
                    empty string to unset the promo code.
                used_codes (defaultdict(int)): A list of codes already used
                    but not added to the session, e.g., in PreregCart.
                    These codes are flattened to the list, as they're only
                    used here to check for used PromoCodeGroup codes.

            Returns:
                str: Either a failure message or an empty string
                    indicating success.
            """
            code = code.strip() if code else ''
            if code:
                attendee.promo_code = self.lookup_promo_code(code, list(used_codes.keys()))
                if attendee.promo_code:
                    attendee.promo_code_id = attendee.promo_code.id
                    return ''
                else:
                    attendee.promo_code_id = None
                    return f"The promo code you entered ({code}) is invalid."
            else:
                attendee.promo_code = None
                attendee.promo_code_id = None
                return ''

        def lookup_promo_code(self, code, used_codes=[]):
            """
            Convenience method for finding a promo code by id or code.
            Accounts for PromoCodeGroups.

            Arguments:
                code (str): The id or code to search for.

            Returns:
                PromoCode: A PromoCode object, either matching
                the given code or found in the matching PromoCodeGroup.
            """
            promo_code = self.lookup_promo_or_group_code(code, PromoCode)
            if promo_code:
                return promo_code

            group = self.lookup_promo_or_group_code(code, PromoCodeGroup)
            if group:
                unused_valid_codes = [code for code in group.valid_codes if code.code not in used_codes]
                return unused_valid_codes[0] if unused_valid_codes else None

        def lookup_promo_or_group_code(self, code, model=PromoCode):
            """
            Convenience method for finding a promo code by id or code.

            Arguments:
                model: Either PromoCode or PromoCodeGroup
                code (str): The id or code to search for.

            Returns:
                Either the matching object of the given model,
                 or None if not found.
            """
            if isinstance(code, uuid.UUID):
                code = code.hex

            normalized_code = PromoCode.normalize_code(code)
            if not normalized_code:
                return None

            unambiguous_code = PromoCode.disambiguate_code(code)
            clause = or_(model.normalized_code == normalized_code, model.normalized_code == unambiguous_code)

            # Make sure that code is a valid UUID before adding
            # PromoCode.id to the filter clause
            try:
                promo_code_id = uuid.UUID(normalized_code).hex
            except Exception:
                pass
            else:
                clause = clause.or_(model.id == promo_code_id)

            return self.query(model).filter(clause).order_by(model.normalized_code.desc()).first()

        def create_promo_code_group(self, attendee, name, badges, cost=None):
            pc_group = PromoCodeGroup(name=name, buyer=attendee)

            self.add_codes_to_pc_group(pc_group, badges, cost)

            return pc_group

        def add_codes_to_pc_group(self, pc_group, badges, cost=None):
            cost = c.get_group_price() if cost is None else cost
            for _ in range(badges):
                self.add(PromoCode(
                    discount=0,
                    discount_type=PromoCode._FIXED_PRICE,
                    uses_allowed=1,
                    group=pc_group,
                    cost=cost))

        def remove_codes_from_pc_group(self, pc_group, badges):
            codes = sorted(pc_group.promo_codes, key=lambda x: x.cost, reverse=True)
            for _ in range(badges):
                code = codes.pop()
                self.delete(code)
                pc_group.promo_codes.remove(code)

        def add_to_print_queue(self, attendee, printer_id, reg_station, print_fee=None, dry_run=False):
            from uber.models import PrintJob
            fields = [
                    'badge_printed_name',
                    'badge_num',
                    'badge_type_label',
                    'ribbon_labels',
                    ]

            errors = []
            if not printer_id:
                errors.append("Printer ID not set.")

            if not reg_station:
                errors.append("Reg station number not set.")

            if print_fee is None and attendee.times_printed > 0:
                errors.append("Please specify what reprint fee to charge this attendee, including $0.")

            if not attendee.birthdate:
                errors.append("Attendee is missing a date of birth.")
            elif not attendee.age_now_or_at_con:
                errors.append("Attendee's date of birth is not recognized as a date.")

            attendee_fields = attendee.to_dict(fields)

            for field in fields:
                if not attendee_fields.get(field) and field != 'ribbon_labels':
                    errors.append("Field missing: {}.".format(field))

            if self.query(PrintJob).filter_by(attendee_id=attendee.id, printed=None, errors="").first():
                errors.append("Badge is already queued to print.")

            if errors:
                return None, errors

            if dry_run:
                return None, None

            print_job = PrintJob(attendee_id=attendee.id,
                                 admin_id=self.current_admin_account().id,
                                 admin_name=self.admin_attendee().full_name,
                                 printer_id=printer_id,
                                 reg_station=reg_station,
                                 print_fee=print_fee)

            if attendee.age_now_or_at_con >= 18:
                print_job.is_minor = False
            else:
                print_job.is_minor = True

            json_data = attendee_fields
            del json_data['_model']
            json_data['attendee_id'] = json_data.pop('id')
            print_job.json_data = json_data

            self.add(print_job)
            self.commit()

            return print_job.id, None

        def update_badge_print_job(self, id):
            job = self.print_job(id)
            attendee = job.attendee

            errors = []

            if attendee.age_group_conf['val'] == c.AGE_UNKNOWN:
                errors.append("Attendee no longer has an age group.")
            else:
                if attendee.age_now_or_at_con < 18 and not job.is_minor:
                    errors.append("Attendee is now under 18, please requeue badge.")
                if attendee.age_now_or_at_con >= 18 and job.is_minor:
                    errors.append("Attendee is no longer under 18, please requeue badge.")

            fields = ['badge_num', 'badge_type_label', 'ribbon_labels', 'badge_printed_name']
            attendee_fields = attendee.to_dict(fields)

            for field in fields:
                if not attendee_fields.get(field) and field != 'ribbon_labels':
                    errors.append("Field missing: {}.".format(field))
                elif attendee_fields.get(field) != job.json_data.get(field):
                    job.json_data[field] = attendee_fields.get(field)

            if not errors:
                self.add(job)
                self.commit()

            return errors

        def get_next_badge_num(self, badge_type):
            """
            Returns the next badge available for a given badge type. This is
            essentially a wrapper for auto_badge_num that accounts for new or
            changed objects in the session.

            Args:
                badge_type: Used to pass to auto_badge_num and to ignore
                    objects in the session that aren't within the badge
                    type's range.

            """
            badge_type = uber.badge_funcs.get_real_badge_type(badge_type)

            new_badge_num = self.auto_badge_num(badge_type)
            lower_bound = c.BADGE_RANGES[badge_type][0]
            upper_bound = c.BADGE_RANGES[badge_type][1]

            # Adjusts the badge number based on badges in the session
            all_models = chain(self.new, self.dirty)
            for attendee in [m for m in all_models if isinstance(m, Attendee)]:
                if attendee.badge_num is not None and lower_bound <= attendee.badge_num <= upper_bound:
                    new_badge_num = max(new_badge_num, 1 + attendee.badge_num)

            assert new_badge_num < upper_bound, 'There are no more badge numbers available in this range!'

            return new_badge_num

        def update_badge(self, attendee, old_badge_type, old_badge_num):
            """
            This should be called whenever an attendee's badge type or badge
            number is changed. It checks if the attendee will still require a
            badge number with their new badge type, and if so, sets their
            number to either the number specified by the admin or the lowest
            available badge number in that range.

            Args:
                attendee: The Attendee() object whose badge is being changed.
                old_badge_type: The old badge type.
                old_badge_num: The old badge number.

            """
            from uber.badge_funcs import needs_badge_num

            if c.SHIFT_CUSTOM_BADGES and c.BEFORE_PRINTED_BADGE_DEADLINE and not c.AT_THE_CON:
                badge_collision = False
                if attendee.badge_num:
                    badge_collision = self.query(Attendee.badge_num).filter(
                        Attendee.badge_num == attendee.badge_num,
                        Attendee.id != attendee.id).first()

                desired_badge_num = attendee.badge_num
                if old_badge_num:
                    if attendee.badge_num and badge_collision:
                        if old_badge_type == attendee.badge_type:
                            if old_badge_num < attendee.badge_num:
                                self.shift_badges(
                                    old_badge_type, old_badge_num + 1, until=attendee.badge_num, down=True)
                            else:
                                self.shift_badges(old_badge_type, attendee.badge_num, until=old_badge_num - 1, up=True)
                        else:
                            self.shift_badges(old_badge_type, old_badge_num + 1, down=True)
                            self.shift_badges(attendee.badge_type, attendee.badge_num, up=True)
                    else:
                        self.shift_badges(old_badge_type, old_badge_num + 1, down=True)

                elif attendee.badge_num and badge_collision:
                    self.shift_badges(attendee.badge_type, attendee.badge_num, up=True)

                attendee.badge_num = desired_badge_num

            if not attendee.badge_num and needs_badge_num(attendee):
                attendee.badge_num = self.get_next_badge_num(attendee.badge_type)

            return 'Badge updated'

        def set_badge_num_in_range(self, attendee):
            """
            A simpler version of update_badge which only makes sure that the attendee's
            current badge number is in their current badge type's range.
            """
            from uber.badge_funcs import get_real_badge_type, needs_badge_num

            if not attendee.badge_num or attendee.checked_in or (c.AFTER_PRINTED_BADGE_DEADLINE
                                                                 and attendee.badge_type in c.PREASSIGNED_BADGE_TYPES):
                return

            badge_type = get_real_badge_type(attendee.badge_type)
            lower_bound, upper_bound = c.BADGE_RANGES[badge_type]
            if not (lower_bound <= attendee.badge_num <= upper_bound):
                attendee.badge_num = None

                if needs_badge_num(attendee):
                    attendee.badge_num = self.get_next_badge_num(attendee.badge_type)

        def auto_badge_num(self, badge_type):
            """
            Gets the next available badge number for a badge type's range.

            Plugins can override the logic here if need be without worrying
            about handling dirty sessions.

            Args:
                badge_type: Used as a starting point if no badges of the same
                    type exist, and to select badges within a specific range.

            """
            in_range = self.query(Attendee.badge_num).filter(
                Attendee.badge_num != None,  # noqa: E711
                Attendee.badge_num >= c.BADGE_RANGES[badge_type][0],
                Attendee.badge_num <= c.BADGE_RANGES[badge_type][1])

            in_range_list = [int(row[0]) for row in in_range.order_by(Attendee.badge_num)]

            if len(in_range_list):
                # Searches badge range for a gap in badge numbers; if none
                # found, returns the latest badge number + 1.
                # Doing this lets admins manually set high badge numbers
                # without filling up the badge type's range.
                start, end = c.BADGE_RANGES[badge_type][0], in_range_list[-1]
                gap_nums = sorted(set(range(start, end + 1)).difference(in_range_list))

                if not gap_nums:
                    return end + 1
                else:
                    return gap_nums[0]
            else:
                return c.BADGE_RANGES[badge_type][0]

        def shift_badges(self, badge_type, badge_num, *, until=None, up=False, down=False):

            if not c.SHIFT_CUSTOM_BADGES or c.AFTER_PRINTED_BADGE_DEADLINE or c.AT_THE_CON:
                return False

            from uber.badge_funcs import get_badge_type
            (calculated_badge_type, error) = get_badge_type(badge_num)
            badge_type = calculated_badge_type or badge_type
            until = until or c.BADGE_RANGES[badge_type][1]

            shift = 1 if up else -1
            query = self.query(Attendee).filter(
                Attendee.badge_num != None,  # noqa: E711
                Attendee.badge_num >= badge_num,
                Attendee.badge_num <= until)

            query.update({Attendee.badge_num: Attendee.badge_num + shift}, synchronize_session='evaluate')

            return True

        def get_next_badge_to_print(self, printer_id=''):
            query = self.query(PrintJob).join(Tracking, PrintJob.id == Tracking.fk_id).filter(
                    PrintJob.printed == None, PrintJob.errors == '', PrintJob.printer_id == printer_id)  # noqa: E711

            badge = query.order_by(Tracking.when.desc()).with_for_update().first()

            return badge

        def valid_attendees(self):
            return self.query(Attendee).filter(Attendee.is_valid == True)  # noqa: E712

        def attendees_with_badges(self):
            return self.query(Attendee).filter(Attendee.has_badge == True)  # noqa: E712

        def all_attendees(self, only_staffing=False, pending=False):
            """
            Returns a Query of Attendees with efficient loading for groups and
            shifts/jobs.

            In some cases we only want to return attendees where "staffing"
            is true, because before the event people can't sign up for shifts
            unless they're marked as volunteers.  However, on-site we relax
            that restriction, so we'll get attendees with shifts who are not
            actually marked as staffing.  We therefore have an optional
            parameter for clients to indicate that all attendees should be
            returned.
            """
            staffing_filter = [Attendee.staffing == True] if only_staffing else []  # noqa: E712

            badge_statuses = [c.NEW_STATUS, c.COMPLETED_STATUS]
            if pending:
                badge_statuses.extend([c.PENDING_STATUS, c.AT_DOOR_PENDING_STATUS])

            badge_filter = Attendee.badge_status.in_(badge_statuses)

            return self.query(Attendee) \
                .filter(badge_filter, *staffing_filter) \
                .options(
                    subqueryload(Attendee.dept_memberships),
                    subqueryload(Attendee.group),
                    subqueryload(Attendee.shifts).subqueryload(Shift.job).subqueryload(Job.department),
                    subqueryload(Attendee.room_assignments)) \
                .order_by(Attendee.full_name, Attendee.id)

        def staffers(self, pending=False):
            return self.all_attendees(only_staffing=True, pending=pending)

        def all_panelists(self):
            return self.query(Attendee).filter(or_(
                Attendee.ribbon.contains(c.PANELIST_RIBBON),
                Attendee.badge_type == c.GUEST_BADGE)).order_by(Attendee.full_name).all()

        @department_id_adapter
        def jobs(self, department_id=None):
            job_filter = {'department_id': department_id} if department_id else {}

            return self.query(Job).filter_by(**job_filter) \
                .options(
                    subqueryload(Job.department),
                    subqueryload(Job.required_roles),
                    subqueryload(Job.shifts).subqueryload(Shift.attendee).subqueryload(Attendee.group)) \
                .order_by(Job.start_time, Job.name)

        def staffers_for_dropdown(self):
            query = self.query(Attendee.id, Attendee.full_name)
            return [
                {'id': id, 'full_name': full_name.title()}
                for id, full_name in query.filter_by(staffing=True).order_by(Attendee.full_name)]

        @department_id_adapter
        def dept_heads(self, department_id=None):
            if department_id:
                return self.query(Department).get(department_id).dept_heads
            return self.query(Attendee).filter(Attendee.dept_memberships.any(is_dept_head=True)) \
                .order_by(Attendee.full_name).all()

        def match_to_group(self, attendee, group):
            available = [a for a in group.attendees if a.is_unassigned]
            if not available:
                return 'The last badge for that group has already been assigned by another station'

            matching = [a for a in available if a.badge_type == attendee.badge_type]
            if not matching:
                return 'Badge #{} is a {} badge, but {} has no badges of that type'.format(
                        attendee.badge_num, attendee.badge_type_label, group.name)
            else:
                # First preserve the attributes to copy to the new group member
                attrs = matching[0].to_dict(attrs=['group', 'group_id', 'paid', 'ribbon'])

                # Then delete the old unassigned group member
                self.delete(matching[0])

                # Flush the deletion so the badge shifting code is performed
                self.flush()

                # Copy the attributes we preserved
                attendee.apply(attrs, restricted=False)

                # Ensure the attendee is added to the session
                self.add(attendee)
                self.commit()

        def get_truth(self, left, op, right):
            # Helper function for use in attribute and property search
            return op(left, right)

        def parse_attr_search_terms(self, search_text):
            # Parse the search terms, including accounting for prefixes like >, <, and !=
            # Returns the target attr/property name, the search term with and without AND/OR, and the operator
            target, term = search_text.split(':', 1)
            target, term = target.strip(), term.strip()
            search_term = term.replace('AND', '').replace('OR', '').strip()

            if search_term and search_term[0] in ['>', '<', '!']:
                if search_term[0] == '!':
                    op = operator.ne

                if search_term[1] == '=':
                    if search_term[0] == '>':
                        op = operator.ge
                    elif search_term[0] == '<':
                        op = operator.le
                    search_term = search_term[2:]
                else:
                    if search_term[0] == '>':
                        op = operator.gt
                    elif search_term[0] == '<':
                        op = operator.lt
                    search_term = search_term[1:]
            else:
                op = operator.eq

            return target, term, search_term, op

        def index_attendees(self):
            # Returns a base attendee query with extra joins for the index page
            attendees = self.query(Attendee).outerjoin(Attendee.group) \
                                            .outerjoin(Attendee.promo_code) \
                                            .outerjoin(PromoCodeGroup, PromoCode.group) \
                                            .options(
                                                joinedload(Attendee.group),
                                                joinedload(Attendee.promo_code).joinedload(PromoCode.group)
                                                )
            if c.ATTENDEE_ACCOUNTS_ENABLED:
                attendees = attendees.outerjoin(Attendee.managers).options(joinedload(Attendee.managers))
            return attendees

        def search(self, text, *filters):
            # We need to both outerjoin on the PromoCodeGroup table and also
            # query it.  In order to do this we need to alias it so that the
            # reference to PromoCodeGroup in the joinedload doesn't conflict
            # with the outerjoin.  See https://docs.sqlalchemy.org/en/13/orm/query.html#sqlalchemy.orm.query.Query.join
            aliased_pcg = aliased(PromoCodeGroup)

            attendees = self.query(Attendee).outerjoin(Attendee.group) \
                                            .outerjoin(Attendee.promo_code) \
                                            .outerjoin(aliased_pcg, PromoCode.group) \
                                            .options(
                                                joinedload(Attendee.group),
                                                joinedload(Attendee.promo_code).joinedload(PromoCode.group)
                                                )
            if c.ATTENDEE_ACCOUNTS_ENABLED:
                attendees = attendees.outerjoin(Attendee.managers).options(joinedload(Attendee.managers))

            attendees = attendees.filter(*filters)

            terms = text.split()
            if len(terms) == 2:
                first, last = terms
                if first.endswith(','):
                    last, first = first.strip(','), last
                name_cond = attendees.icontains_condition(first_name=first, last_name=last)
                legal_name_cond = attendees.icontains_condition(legal_name="{}%{}".format(first, last))
                first_name_cond = attendees.icontains_condition(first_name=terms)
                last_name_cond = attendees.icontains_condition(last_name=terms)
                if attendees.filter(or_(name_cond, legal_name_cond, first_name_cond, last_name_cond)).first():
                    return attendees.filter(or_(name_cond, legal_name_cond, first_name_cond, last_name_cond)), ''

            elif len(terms) == 1 and terms[0].endswith(','):
                last = terms[0].rstrip(',')
                name_cond = attendees.icontains_condition(last_name=last)
                # Known issue: search includes first name if legal name is set
                legal_cond = attendees.icontains_condition(legal_name=last)
                return attendees.filter(or_(name_cond, legal_cond)), ''

            elif len(terms) == 1 and terms[0].isdigit():
                if len(terms[0]) == 10:
                    return attendees.filter(or_(Attendee.ec_phone == terms[0], Attendee.cellphone == terms[0])), ''
                elif int(terms[0]) <= sorted(
                        c.BADGE_RANGES.items(),
                        key=lambda badge_range: badge_range[1][0])[-1][1][1]:
                    return attendees.filter(Attendee.badge_num == terms[0]), ''

            elif len(terms) == 1 \
                    and re.match('^[a-z0-9]{8}-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{12}$', terms[0]):

                id_list = [
                    Attendee.id == terms[0],
                    Attendee.public_id == terms[0],
                    aliased_pcg.id == terms[0],
                    Group.id == terms[0],
                    Group.public_id == terms[0]]

                if c.ATTENDEE_ACCOUNTS_ENABLED:
                    id_list.extend([AttendeeAccount.id == terms[0], AttendeeAccount.public_id == terms[0]])

                return attendees.filter(or_(*id_list)), ''

            elif len(terms) == 1 and terms[0].startswith(c.EVENT_QR_ID):
                search_uuid = terms[0][len(c.EVENT_QR_ID):]
                if re.match('^[a-z0-9]{8}-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{12}$', search_uuid):
                    return attendees.filter(or_(
                        Attendee.public_id == search_uuid,
                        Group.public_id == search_uuid)), ''

            or_checks = []
            and_checks = []

            def check_text_fields(search_text):
                check_list = [
                    Group.name.ilike('%' + search_text + '%'),
                    aliased_pcg.name.ilike('%' + search_text + '%'),
                ]

                if c.ATTENDEE_ACCOUNTS_ENABLED:
                    check_list.append(AttendeeAccount.email.ilike('%' + search_text + '%'))

                for attr in Attendee.searchable_fields:
                    check_list.append(getattr(Attendee, attr).ilike('%' + search_text + '%'))

                return check_list

            if ':' in text:
                delimited_text = text.replace('AND', 'AND,').replace('OR', 'OR,')
                list_of_attr_searches = delimited_text.split(',')
                last_term = None

                for search_text in list_of_attr_searches:
                    if ':' not in search_text:
                        last_term = search_text
                        search_text = search_text.replace('AND', '').replace('OR', '').strip()
                        or_checks.extend(check_text_fields(search_text))
                    else:
                        target, term, search_term, op = self.parse_attr_search_terms(search_text)

                        if target == 'email':
                            attr_search_filter = Attendee.normalized_email.contains(normalize_email_legacy(search_term))
                        elif target == 'account_email':
                            attr_search_filter = AttendeeAccount.normalized_email.contains(
                                normalize_email_legacy(search_term))
                        elif target == 'group':
                            attr_search_filter = Group.normalized_name.contains(search_term.strip().lower())
                        elif target == 'has_ribbon':
                            attr_search_filter = Attendee.ribbon.contains(
                                Attendee.ribbon.type.convert_if_labels(search_term.title()))
                        elif target in Attendee.searchable_bools:
                            t_or_f = search_term.strip().lower() not in ('f', 'false', 'n', 'no', '0', 'none')
                            attr_search_filter = getattr(Attendee, target) == t_or_f

                            if not isinstance(getattr(Attendee, target).type, Boolean):
                                attr_search_filter = getattr(Attendee, target) != None \
                                    if t_or_f == True else getattr(Attendee, target) == None  # noqa: E711, E712
                        elif target in Attendee.searchable_choices:
                            if target == 'amount_extra':
                                # Allow searching kick-in by dollar value and not just the label
                                try:
                                    search_term = int(search_term.replace('$', ''))
                                except Exception:
                                    pass
                            else:
                                try:
                                    search_term = getattr(Attendee, target).type.convert_if_label(search_term)
                                except KeyError:
                                    # A lot of our labels are title-cased
                                    try:
                                        search_term = getattr(Attendee, target
                                                              ).type.convert_if_label(search_term.title())
                                    except KeyError:
                                        return None, 'ERROR: {} is not a valid option for {}'.format(search_term,
                                                                                                     target)
                            attr_search_filter = self.get_truth(getattr(Attendee, target), op, search_term)
                        else:
                            try:
                                getattr(Attendee, target)
                            except AttributeError:
                                return None, 'ERROR: {} is not a valid attribute'.format(target)
                            # Are we a searchable property?
                            if isinstance(getattr(Attendee, target) == search_term,
                                          sqlalchemy.sql.elements.BinaryExpression):
                                attr_search_filter = self.get_truth(getattr(Attendee, target), op, search_term)
                            else:
                                return None, 'ERROR: {} is not a searchable attribute'.format(target)

                        if term.endswith(' OR') or last_term and last_term.endswith(' OR'):
                            or_checks.append(attr_search_filter)
                        else:
                            and_checks.append(attr_search_filter)

                        last_term = term
            else:
                or_checks.extend(check_text_fields(text))

            if or_checks and and_checks:
                return attendees.filter(or_(*or_checks), and_(*and_checks)), ''
            elif or_checks:
                return attendees.filter(or_(*or_checks)), ''
            elif and_checks:
                return attendees.filter(and_(*and_checks)), ''
            else:
                return attendees, ''

        def property_search(self, text):
            """
            Many of our most useful forms of data are properties on the Attendee model.
            However, these often are too complex to create SQL statements for, so we
            can't use them in regular attendee attribute search. Our workaround for this
            has been either creating custom reports or making sysadmins cry. This is our
            quick-ish solution -- a way to filter attendees by any property. Because this is
            resource-intensive, it is locked behind the Devtools site section.
            """
            if "OR" in text:
                return None, 'Sorry, property search does not currently support OR conditions.'
            delimited_text = text.replace('AND', 'AND,')
            list_of_attr_searches = delimited_text.split(',')

            conditions_list = []
            results = []

            for search_text in list_of_attr_searches:
                target, term, search_term, op = self.parse_attr_search_terms(search_text)
                try:
                    search_term = int(search_term)
                except Exception:
                    pass
                conditions_list.append((target, search_term, op))

            for attendee in self.valid_attendees():
                if all([self.get_truth(getattr(attendee, target), op, search_term)
                        for target, search_term, op in conditions_list]):
                    results.append(attendee)

            return results, ''

        def delete_from_group(self, attendee, group):
            """
            Sometimes we want to delete an attendee badge which is part of a
            group.  In most cases, we could just say "session.delete(attendee)"
            but sometimes we need to make sure that the attendee is ALSO
            removed from the "group.attendees" list before we commit, since the
            number of attendees in a group is used in our presave_adjustments()
            code to update the group price.  So anytime we delete an attendee
            in a group, we should use this method.
            """
            self.delete(attendee)
            group.attendees.remove(attendee)

        def assign_badges(
                self, group, new_badge_count, new_badge_type=c.ATTENDEE_BADGE,
                new_ribbon_type=None, paid=c.PAID_BY_GROUP,
                **extra_create_args):

            diff = int(new_badge_count) - group.badges
            sorted_unassigned = sorted(group.floating, key=lambda a: a.registered, reverse=True)
            ribbon_to_use = ','.join(map(str, listify(new_ribbon_type))) if new_ribbon_type else group.new_ribbon

            if int(new_badge_type) in c.PREASSIGNED_BADGE_TYPES and c.AFTER_PRINTED_BADGE_DEADLINE and diff > 0:
                return 'Custom badges have already been ordered, so you will need to select a different badge type'
            elif diff > 0:
                for i in range(diff):
                    new_attendee = Attendee(
                        badge_type=new_badge_type,
                        ribbon=ribbon_to_use,
                        paid=paid,
                        **extra_create_args)
                    group.attendees.append(new_attendee)

            elif diff < 0:
                if len(group.floating) < abs(diff):
                    return 'You cannot reduce the number of badges for a group to below the number of assigned badges'
                else:
                    for attendee in sorted_unassigned[:abs(diff)]:
                        self.delete_from_group(attendee, group)

        def assign(self, attendee_id, job_id):
            """
            assign an Attendee to a Job by creating a Shift
            :return: 'None' on success, error message on failure
            """
            job = self.job(job_id)
            attendee = self.attendee(attendee_id)

            if not attendee.has_required_roles(job):
                return 'You cannot assign an attendee to this shift who does not have the required roles: {}'.format(
                    job.required_roles_labels)

            if job.slots <= len(job.shifts):
                return 'All slots for this job have already been filled'

            if not job.no_overlap(attendee):
                return 'This volunteer is already signed up for a shift during that time'

            if not job.working_limit_ok(attendee):
                return 'This shift would put this volunteer over one of their department\'s max consecutive hours'

            self.add(Shift(attendee=attendee, job=job))
            self.commit()

        def insert_test_admin_account(self):
            """
            Insert a test admin into the database with username
            "magfest@example.com" password "magfest" this is ONLY allowed if
            no other admins already exist in the database.

            Returns:
                bool: True if success, False if failure
            """
            if self.query(AdminAccount).first() is not None:
                return False

            attendee = Attendee(
                placeholder=True,
                first_name='Test',
                last_name='Developer',
                email=c.TEST_ADMIN_EMAIL,
                badge_type=c.ATTENDEE_BADGE,
            )
            self.add(attendee)

            all_access_group = AccessGroup(
                name='All Access',
                access={section: '5' for section in c.ADMIN_PAGES}
            )

            test_developer_account = AdminAccount(
                attendee=attendee,
            )

            if not c.SAML_SETTINGS:
                test_developer_account.hashed = create_new_hash('magfest')

            test_developer_account.access_groups.append(all_access_group)

            self.add(all_access_group)
            self.add(test_developer_account)
            self.commit()

            return True

        def set_relation_ids(self, instance, field, cls, value):
            values = set(s for s in listify(value) if s and s != 'None')
            relations = self.query(cls).filter(cls.id.in_(values)).all() if values else []
            setattr(instance, field, relations)

        def bulk_insert(self, models):
            """
            Convenience method for bulk inserting model objects.

            In general, doing a bulk insert is much faster than individual
            inserts, but the whole insert will fail if a single object
            violates the database's referential integrity.

            This function does a bulk insert, but if an `IntegrityError` is
            encountered, it falls back to inserting the model objects
            one-by-one, and ignores the individual integrity errors.

            Arguments:
                models (list): A list of sqlalchemy model objects.

            Returns:
                list: A list of model objects that was succesfully inserted.
                    The returned list will not include any model objects that
                    failed insertion.
            """
            for model in models:
                model.presave_adjustments()
            try:
                self.bulk_save_objects(models)
                self.commit()
                return models
            except IntegrityError as error:
                log.debug('Bulk insert failed: {}', error)
                self.rollback()

                # Bulk insert failed, so insert one at a time and ignore errors
                inserted_models = []
                for model in models:
                    try:
                        self.add(model)
                        self.commit()
                        inserted_models.append(model)
                    except IntegrityError:
                        log.debug('Individual insert failed: {}', error)
                        # Ignore db integrity errors
                        self.rollback()
                return inserted_models

        # ========================
        # mivs
        # ========================

        def logged_in_studio(self):
            try:
                return self.indie_studio(cherrypy.session.get('studio_id'))
            except Exception:
                raise HTTPRedirect('../mivs/studio')

        def logged_in_judge(self):
            judge = self.admin_attendee().admin_account.judge
            if judge:
                return judge
            else:
                raise HTTPRedirect(
                    '../accounts/homepage?message={}',
                    'You have been given judge access but not had a judge entry created for you - '
                    'please contact a MIVS admin to correct this.')

        def code_for(self, game):
            if game.unlimited_code:
                return game.unlimited_code
            else:
                for code in self.logged_in_judge().codes:
                    if code.game == game:
                        return code

        def delete_screenshot(self, screenshot):
            self.delete(screenshot)
            try:
                os.remove(screenshot.filepath)
            except Exception:
                pass
            self.commit()

        def indie_judges(self):
            return self.query(IndieJudge).join(IndieJudge.admin_account).join(AdminAccount.attendee) \
                .order_by(Attendee.full_name)

        def indie_games(self):
            return self.query(IndieGame).join(IndieStudio).options(
                joinedload(IndieGame.studio), joinedload(IndieGame.reviews)).order_by(IndieStudio.name, IndieGame.title)

        # =========================
        # mits
        # =========================

        def log_in_as_mits_team(
                self, team_id, redirect_to='../mits/index'):
            try:
                team = self.mits_team(team_id)
                duplicate_teams = []
                while team.duplicate_of:
                    duplicate_teams.append(team.id)
                    team = self.mits_team(team.duplicate_of)
                    assert team.id not in duplicate_teams, 'circular reference in duplicate_of: {}'.format(
                        duplicate_teams)
            except Exception:
                log.error('attempt to log into invalid team {}', team_id, exc_info=True)
                raise HTTPRedirect('../mits/login_explanation')
            else:
                cherrypy.session['mits_team_id'] = team.id
                raise HTTPRedirect(redirect_to)

        def logged_in_mits_team(self):
            try:
                team = self.mits_team(cherrypy.session.get('mits_team_id'))
                assert not team.deleted or team.duplicate_of
            except Exception:
                raise HTTPRedirect('../mits/login_explanation')
            else:
                if team.duplicate_of:
                    # The currently-logged-in team was deleted, so log
                    # back in as the correct team.
                    self.log_as_as_mits_team(team.id)
                else:
                    return team

        def mits_teams(self, include_deleted=False):
            if include_deleted:
                deleted_filter = []
            else:
                deleted_filter = [MITSTeam.deleted == False]  # noqa: E712
            return self.query(MITSTeam).filter(*deleted_filter).options(
                joinedload(MITSTeam.applicants).subqueryload(MITSApplicant.attendee),
                joinedload(MITSTeam.games),
                joinedload(MITSTeam.schedule),
            ).order_by(MITSTeam.name)

        def delete_mits_file(self, model):
            try:
                os.remove(model.filepath)
            except Exception:
                log.error('Unexpected error deleting MITS file {}', model.filepath)

            # Regardless of whether removing the file from the
            # filesystem succeeded, we still want the delete it from the
            # database. The most likely cause of failure is if the file
            # was already deleted or is otherwise not present, so it
            # wouldn't make sense to keep the database record around.
            self.delete(model)
            self.commit()

        # =========================
        # panels
        # =========================

        def panel_apps(self):
            return self.query(PanelApplication).order_by('applied').all()

        def panel_applicants(self):
            return self.query(PanelApplicant).options(joinedload(PanelApplicant.application)) \
                .order_by('first_name', 'last_name')

    @classmethod
    def model_mixin(cls, model):
        if model.__name__ in ['SessionMixin', 'QuerySubclass']:
            target = getattr(cls, model.__name__)
        else:
            for target in cls.all_models():
                if target.__name__ == model.__name__:
                    break
            else:
                raise ValueError('No existing model with name {}'.format(model.__name__))

        for name in dir(model):
            if not name.startswith('_'):
                attr = getattr(model, name)
                if hasattr(target, '__table__') and name in target.__table__.c:
                    attr.key = attr.key or name
                    attr.name = attr.name or name
                    attr.table = target.__table__
                    target.__table__.c.replace(attr)
                else:
                    setattr(target, name, attr)
        return target


def initialize_db(modify_tables=False):
    """
    Initialize the session on startup.

    We want to do this only after all other plugins have had a chance to
    initialize and add their 'mixin' data (i.e. extra columns) into the models.

    Also, it's possible that the DB is still initializing and isn't ready to
    accept connections, so, if this fails, keep trying until we're able to
    connect.

    This should be the ONLY spot (except for maintenance tools) in all of core
    ubersystem or any plugins that attempts to create tables by passing
    drop=True or modify_tables=True or initialize=True to
    Session.initialize_db()
    """
    for i in range(20):
        try:
            Session.initialize_db(modify_tables=modify_tables, initialize=True)
            return
        except KeyboardInterrupt:
            log.critical('DB initialize: Someone hit Ctrl+C while we were starting up')
        except Exception:
            traceback.print_exc()
        log.info(f"Database initialization failed. (Attempt {i+1} / 20)")
        time.sleep(i**i)
cherrypy.engine.subscribe('start', initialize_db, priority=99)

def _attendee_validity_check():
    orig_getter = Session.SessionMixin.attendee

    @wraps(orig_getter)
    def with_validity_check(self, *args, **kwargs):
        allow_invalid = kwargs.pop('allow_invalid', False)
        attendee = orig_getter(self, *args, **kwargs)
        if not allow_invalid and not attendee.is_new and \
           not self.current_admin_account and not attendee.is_valid:
            raise HTTPRedirect('../preregistration/invalid_badge?id={}', attendee.id)
        else:
            return attendee
    Session.SessionMixin.attendee = with_validity_check
cherrypy.engine.subscribe('start', _attendee_validity_check, priority=98)

def _presave_adjustments(session, context, instances='deprecated'):
    for model in chain(session.dirty, session.new):
        model.presave_adjustments()
    for model in session.deleted:
        model.predelete_adjustments()


def _track_changes(session, context, instances='deprecated'):
    states = [
        (c.CREATED, session.new),
        (c.UPDATED, session.dirty),
        (c.DELETED, session.deleted)]

    for action, instances in states:
        for instance in instances:
            if instance.__class__ not in Tracking.UNTRACKED:
                Tracking.track(action, instance)


def register_session_listeners():
    """
    The order in which we register these listeners matters.
    """
    listen(Session.session_factory, 'before_flush', _presave_adjustments)
    listen(Session.session_factory, 'after_flush', _track_changes)


def _track_collection_append(target, value, initiator):
    Tracking.track_collection_change(c.ITEM_ADDED, target, value)


def _track_collection_remove(target, value, initiator):
    Tracking.track_collection_change(c.ITEM_REMOVED, target, value)


def register_attribute_listeners():
    """
    Many-to-many tables aren't tracked via the session listener.
    This registers all collections that we want to track explicitly.
    """
    for collection in [
        AdminAccount.access_groups,
        AttendeeAccount.attendees,
        DeptRole.dept_memberships,
        Job.required_roles,
    ]:
        listen(collection, 'append', _track_collection_append, propagate=True)
        listen(collection, 'remove', _track_collection_remove, propagate=True)


register_session_listeners()
register_attribute_listeners()
