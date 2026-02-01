from collections.abc import Mapping
from collections import OrderedDict
from datetime import datetime, time, timedelta
from PIL import Image
import re
import shutil

import pytz
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import relationship
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.schema import Column
from sqlalchemy.sql.expression import FunctionElement
from sqlalchemy.types import Boolean, Integer, TypeDecorator, String, DateTime, Uuid, JSON

from uber.config import c, _config as config
from uber.utils import url_domain, listify, camel

__all__ = [
    'default_relationship', 'relationship', 'utcmin', 'utcnow', 'Choice',
    'Column', 'DefaultColumn', 'MultiChoice',
    'TakesPaymentMixin', 'GuidebookImageMixin']


def DefaultColumn(*args, admin_only=False, private=False, **kwargs):
    """
    Returns a SQLAlchemy Column with the given parameters, except that instead
    of the regular defaults, we've overridden the following defaults if no
    value is provided for the following parameters:

        Field           Old Default     New Default
        -----           ------------    -----------
        nullable        True            False
        default         None            ''  (only for String fields)
        server_default  None            <same value as 'default'>

    We also have an "admin_only" parameter, which is set as an attribute on
    the column instance, indicating whether the column should be settable by
    regular attendees filling out one of the registration forms or if only a
    logged-in admin user should be able to set it.
    """
    kwargs.setdefault('nullable', False)
    type_ = args[0]
    if type_ is String or isinstance(type_, (String, MultiChoice)):
        kwargs.setdefault('default', '')
    default = kwargs.get('default')
    if isinstance(default, (int, str)):
        kwargs.setdefault('server_default', str(default))
    col = SQLAlchemy_Column(*args, **kwargs)
    col.admin_only = admin_only or type_ in (Uuid(as_uuid=False), DateTime)
    col.private = private
    return col


def default_relationship(*args, **kwargs):
    """
    Returns a SQLAlchemy relationship with the given parameters, except that
    instead of the regular defaults, we've overridden the following defaults
    if no value is provided for the following parameters:
        load_on_pending now defaults to True
        cascade now defaults to 'all,delete-orphan'
    """
    kwargs.setdefault('load_on_pending', True)
    if kwargs.get("viewonly", False):
        # Recent versions of SQLAlchemy won't allow cascades that cause writes
        # on viewonly relationships.
        kwargs.setdefault('cascade', 'expunge,refresh-expire,merge')
    else:
        kwargs.setdefault('cascade', 'all,delete-orphan')
    return SQLAlchemy_relationship(*args, **kwargs)


# Alias Column and relationship to maintain backwards compatibility
class SQLAlchemy_Column(Column):
    admin_only = None

Column = DefaultColumn
SQLAlchemy_relationship, relationship = relationship, default_relationship


class utcmax(FunctionElement):
    """
    Exactly the same as utcnow(), but uses '9999-12-31 23:59' instead of now.

    See utcmin and utcnow for more details.

    """
    datetime = datetime(9999, 12, 31, 23, 59, 59, tzinfo=pytz.UTC)
    type = DateTime(timezone=True)


@compiles(utcmax, 'postgresql')
def pg_utcmax(element, compiler, **kw):
    return "timezone('utc', '9999-12-31 23:59:59')"


@compiles(utcmax, 'sqlite')
def sqlite_utcmax(element, compiler, **kw):
    return "(datetime('9999-12-31 23:59:59', 'utc'))"


class utcmin(FunctionElement):
    """
    Exactly the same as utcnow(), but uses '0001-01-01 00:00' instead of now.

    Useful for datetime columns that you would like to index. We often need
    to create datetime columns that are NULL until a particular event happens,
    like an attendee checks in to an event. For those columns that we'd like
    to query (either for "IS NULL", or "IS NOT NULL"), an index isn't helpful,
    because Postgres doesn't index NULL values.

    In those cases where we'd like to query against a NULL datetime column,
    instead of using NULLable, we can use a NOT NULL datetime column, and make
    the default value utcmin(). We can consider any value in the column
    greater than '0001-01-01 00:00' to be NOT NULL.

    Instead of::

        Attendee.checkin_time != None

    We can get the benefits of indexing by doing::

        Attendee.checkin_time > utcmin.datetime

    """
    datetime = datetime(1, 1, 1, 0, 0, 0, tzinfo=pytz.UTC)
    type = DateTime(timezone=True)


@compiles(utcmin, 'postgresql')
def pg_utcmin(element, compiler, **kw):
    return "timezone('utc', '0001-01-01 00:00')"


@compiles(utcmin, 'sqlite')
def sqlite_utcmin(element, compiler, **kw):
    return "(datetime('0001-01-01 00:00', 'utc'))"


class utcnow(FunctionElement):
    """
    We have some tables where we want to save a timestamp on each row
    indicating when the row was first created.  Normally we could do something
    like this::

        created = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

    Unfortunately, there are some cases where we instantiate a model and then
    don't save it until sometime later.  This happens when someone registers
    themselves and then doesn't pay until later, since we don't save them to
    the database until they've paid.  Therefore, we use this class so that we
    can set a timestamp based on when the row was inserted rather than when
    the model was instantiated::

        created = Column(DateTime(timezone=True), server_default=utcnow(), default=lambda: datetime.now(UTC))

    The pg_utcnow and sqlite_utcnow functions below define the implementation
    for postgres and sqlite, and new functions will need to be written if/when
    we decided to support other databases.
    """
    type = DateTime(timezone=True)


@compiles(utcnow, 'postgresql')
def pg_utcnow(element, compiler, **kw):
    return "timezone('utc', current_timestamp)"


@compiles(utcnow, 'sqlite')
def sqlite_utcnow(element, compiler, **kw):
    return "(datetime('now', 'utc'))"


class Choice(TypeDecorator):
    """
    Utility class for storing the results of a dropdown as a database column.
    """
    impl = Integer
    cache_ok = True

    def __init__(self, choices, *, allow_unspecified=False, **kwargs):
        """
        Args:
            choices: an array of tuples, where the first element of each tuple
                is the integer being stored and the second element is a string
                description of the value.
            allow_unspecified: by default, an exception is raised if you try
                to save a row with a value which is not in the choices list
                passed to this class; set this to True if you want to allow
                non-default values.
        """
        self.choices = dict(choices)
        self.allow_unspecified = allow_unspecified
        TypeDecorator.__init__(self, **kwargs)

    def process_bind_param(self, value, dialect):
        if value is not None:
            value = self.convert_if_label(value)
            try:
                assert self.allow_unspecified or int(value) in self.choices
            except Exception:
                raise ValueError('{!r} not a valid option out of {}'.format(
                    value, self.choices))
            else:
                return int(value)

    def process_result_value(self, value, dialect):
        """
        We allow inserting and updating Choice columns using a label (str), rather than the
        literal value (int). However, in some cases we access the value from the database
        BEFORE the label is converted into the value, so we must also convert it here.
        """
        if value is not None:
            value = self.convert_if_label(value)
        return value

    def convert_if_label(self, value):
        try:
            int(value)
        except ValueError:
            # This is a string, is it the label?
            label_lookup = {val: key for key, val in self.choices.items()}
            label_lookup['Unknown'] = -1
            return label_lookup[value]
        return int(value)


class UniqueList(TypeDecorator):
    """
    Utility class for storing a list of unique strings or integers.
    The list is stored as a comma-separate string.
    """
    impl = String
    inherit_cache = True

    def process_bind_param(self, value, dialect):
        """
        A unique list may be in one of three forms: a single string,
        a single integer, or a list of strings. We want to end up with a single
        comma-separated string. We also want to make sure an object has only
        unique values in its UniqueList columns. Therefore, we listify() the
        object to make sure it's in list form, we convert it to a set to
        make all the values unique, and we map the values inside it to strings
        before joining them with commas because the join function can't handle
        a list of integers.
        """
        return ','.join(map(str, list(set(listify(value))))) if value else ''


class MultiChoice(UniqueList):
    """
    Utility class for storing the results of a group of checkboxes. Each value
    is represented by an integer, so we store them as a comma-separated string.
    This can be marginally more convenient than a many-to-many table. Like the
    Choice class, this takes an array of tuples of integers and strings.
    """
    impl = String
    inherit_cache = True

    def __init__(self, choices, **kwargs):
        self.choices = choices
        self.choices_dict = dict(choices)
        UniqueList.__init__(self, **kwargs)

    def process_result_value(self, value, dialect):
        """
        We allow inserting and updating MultiChoice columns using a set of labels (str), rather than the
        literal values. However, in some cases we access the value from the database
        BEFORE the labels are converted into the values, so we must also convert them here.
        """
        if value is not None:
            value = self.convert_if_labels(value)
        return value

    def convert_if_labels(self, value):
        try:
            int(listify(value)[0])
        except ValueError:
            # This is a string list, is it the labels?
            try:
                label_lookup = {val: key for key, val in self.choices}
                label_lookup['Unknown'] = -1
            except TypeError:
                # The labels are unhashable, probably just a string list of the int values
                return value
            try:
                vals = [label_lookup[label] for label in re.split(r'; |, |\*|\n| / ', value)]  # noqa: W605
            except KeyError:
                # It's probably just a string list of the int values
                return value
            value = ','.join(map(str, vals))
        return value


class GuidebookImageMixin():
    filename = Column(String)
    content_type = Column(String)
    extension = Column(String)
    is_header = Column(Boolean, default=False)
    is_thumbnail = Column(Boolean, default=False)

    @property
    def url(self):
        raise NotImplementedError

    @property
    def filepath(self):
        raise NotImplementedError

    @classmethod
    def upload_image(cls, pic, **kwargs):
        new_pic = cls(
            filename=pic.filename,
            content_type=pic.content_type.value,
            extension=pic.filename.split('.')[-1].lower()
            )
        for key, val in kwargs.items():
            if hasattr(new_pic, key):
                setattr(new_pic, key, val)

        with open(new_pic.filepath, 'wb') as f:
            shutil.copyfileobj(pic.file, f)
        return new_pic

    def check_image_size(self, size_list=None):
        if not size_list:
            size_list = c.GUIDEBOOK_HEADER_SIZE if self.is_header else c.GUIDEBOOK_THUMBNAIL_SIZE
        try:
            return Image.open(self.filepath).size == tuple(map(int, size_list))
        except OSError:
            # This probably isn't an image at all
            return


class TakesPaymentMixin(object):
    @property
    def payment_deadline(self):
        return min(
            c.UBER_TAKEDOWN - timedelta(days=2),
            datetime.combine((self.registered + timedelta(days=14)).date(), time(23, 59)))
