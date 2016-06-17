from uber.common import *


def _get_defaults(func):
    spec = inspect.getfullargspec(func)
    return dict(zip(reversed(spec.args), reversed(spec.defaults)))
default_constructor = _get_defaults(declarative.declarative_base)['constructor']


SQLAlchemyColumn = Column
sqlalchemy_relationship = relationship


def Column(*args, admin_only=False, **kwargs):
    """
    Returns a SQLAlchemy Column with the given parameters, except that instead
    of the regular defaults, we've overridden the following defaults if no
    value is provided for the following parameters:

        Field           Old Default     New Default
        -----           ------------    -----------
        nullable        True            False
        default         None            ''  (only for UnicodeText fields)
        server_default  None            <same value as 'default'>

    We also have an "admin_only" parameter, which is set as an attribute on
    the column instance, indicating whether the column should be settable by
    regular attendees filling out one of the registration forms or if only a
    logged-in admin user should be able to set it.
    """
    kwargs.setdefault('nullable', False)
    if args[0] is UnicodeText or isinstance(args[0], (UnicodeText, MultiChoice)):
        kwargs.setdefault('default', '')
    default = kwargs.get('default')
    if isinstance(default, (int, str)):
        kwargs.setdefault('server_default', str(default))
    col = SQLAlchemyColumn(*args, **kwargs)
    col.admin_only = admin_only or args[0] in [UUID, UTCDateTime]
    return col


def relationship(*args, **kwargs):
    """
    Returns a SQLAlchemy relationship with the given parameters, except that
    instead of the regular defaults, we've overridden the following defaults if
    no value is provided for the following parameters:
        load_on_pending now defaults to True
        cascade now defaults to 'all,delete-orphan'
    """
    kwargs.setdefault('load_on_pending', True)
    kwargs.setdefault('cascade', 'all,delete-orphan')
    return sqlalchemy_relationship(*args, **kwargs)


class utcnow(FunctionElement):
    """
    We have some tables where we want to save a timestamp on each row indicating
    when the row was first created.  Normally we could do something like this:

        created = Column(UTCDateTime, default=lambda: datetime.now(UTC))

    Unfortunately, there are some cases where we instantiate a model and then
    don't save it until sometime later.  This happens when someone registers
    themselves and then doesn't pay until later, since we don't save them to the
    database until they've paid.  Therefore, we use this class so that we can
    set a timestamp based on when the row was inserted rather than when the
    model was instantiated:

        created = Column(UTCDateTime, server_default=utcnow())

    The pg_utcnow and sqlite_utcnow functions below define the implementation
    for postgres and sqlite, and new functions will need to be written if/when
    we decided to support other databases.
    """
    type = UTCDateTime()


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

    def __init__(self, choices, *, allow_unspecified=False, **kwargs):
        """
        choices: an array of tuples, where the first element of each tuple is
                 the integer being stored and the second element is a string
                 description of the value
        allow_unspecified: by default, an exception is raised if you try to save
                           a row with a value which is not in the choices list
                           passed to this class; set this to True if you want to
                           allow non-default values
        """
        self.choices = dict(choices)
        self.allow_unspecified = allow_unspecified
        TypeDecorator.__init__(self, **kwargs)

    def process_bind_param(self, value, dialect):
        if value is not None:
            try:
                assert self.allow_unspecified or int(value) in self.choices
            except:
                raise ValueError('{!r} not a valid option out of {}'.format(value, self.choices))
            else:
                return int(value)


class MultiChoice(TypeDecorator):
    """
    Utility class for storing the results of a group of checkboxes.  Each value
    is represented by an integer, so we store them as a comma-separated string.
    This can be marginally more convenient than a many-to-many table.  Like the
    Choice class, this takes an array of tuples of integers and strings.
    """
    impl = UnicodeText

    def __init__(self, choices, **kwargs):
        self.choices = choices
        TypeDecorator.__init__(self, **kwargs)

    def process_bind_param(self, value, dialect):
        return value if isinstance(value, str) else ','.join(value)


@declarative_base
class MagModel:
    id = Column(UUID, primary_key=True, default=lambda: str(uuid4()))

    required = ()

    def __init__(self, *args, **kwargs):
        if '_model' in kwargs:
            assert kwargs.pop('_model') == self.__class__.__name__
        default_constructor(self, *args, **kwargs)
        for attr, col in self.__table__.columns.items():
            if col.default:
                self.__dict__.setdefault(attr, col.default.execute())

    @property
    def _class_attrs(self):
        return {name: getattr(self.__class__, name) for name in dir(self.__class__)}

    def _invoke_adjustment_callbacks(self, label):
        callbacks = []
        for name, attr in self._class_attrs.items():
            if hasattr(attr, '__call__') and hasattr(attr, label):
                callbacks.append(getattr(self, name))
        callbacks.sort(key=lambda f: getattr(f, label))
        for func in callbacks:
            func()

    def presave_adjustments(self):
        self._invoke_adjustment_callbacks('presave_adjustment')

    def predelete_adjustments(self):
        self._invoke_adjustment_callbacks('predelete_adjustment')

    @property
    def addons(self):
        """
        This exists only to be overridden by other events; it should return a
        list of strings are the extra things which an attendee or group has
        purchased.  For example, in the MAGStock codebase, we've got code which
        looks something like this:

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

    @property
    def cost_property_names(self):
        """Returns the names of all cost properties on this model."""
        return [name for name, attr in self._class_attrs.items() if isinstance(attr, cost_property)]

    @property
    def default_cost(self):
        """
        Returns the sum of all @cost_property values for this model instance.
        Because things like discounts exist, we ensure cost can never be negative.
        """
        return max(0, sum([getattr(self, name) for name in self.cost_property_names], 0))

    @class_property
    def unrestricted(cls):
        """
        Returns a set of column names which are allowed to be set by non-admin
        attendees filling out one of the registration forms.
        """
        return {col.name for col in cls.__table__.columns if not getattr(col, 'admin_only', True)}

    @class_property
    def all_bools(cls):
        """Returns the set of Boolean column names for this table."""
        return {col.name for col in cls.__table__.columns if isinstance(col.type, Boolean)}

    @class_property
    def all_checkgroups(cls):
        """Returns the set of MultiChoice column names for this table."""
        return {col.name for col in cls.__table__.columns if isinstance(col.type, MultiChoice)}

    @class_property
    def regform_bools(cls):
        """Returns the set of non-admin-only Boolean columns for this table."""
        return {colname for colname in cls.all_bools if colname in cls.unrestricted}

    @class_property
    def regform_checkgroups(cls):
        """Returns the set of non-admin-only MultiChoice columns for this table."""
        return {colname for colname in cls.all_checkgroups if colname in cls.unrestricted}

    @property
    def session(self):
        """
        Returns the session object which this model instance is attached to, or
        None if this instance is not attached to a session.
        """
        return Session.session_factory.object_session(self)

    @classmethod
    def get_field(cls, name):
        """Returns the column object with the provided name for this model."""
        return cls.__table__.columns[name]

    def __eq__(self, m):
        return self.id is not None and isinstance(m, MagModel) and self.id == m.id

    def __ne__(self, m):        # Python is stupid for making me do this
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
        choices = dict(self.get_field(name).type.choices)
        return [int(i) for i in str(val).split(',') if int(i) in choices] if val else []

    @suffix_property
    def _label(self, name, val):
        return '' if val is None else self.get_field(name).type.choices[int(val)]

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

        try:
            [multi] = [col for col in self.__table__.columns if isinstance(col.type, MultiChoice)]
            choice = getattr(c, name)
            assert choice in [val for val, desc in multi.type.choices]
        except:
            pass
        else:
            return choice in getattr(self, multi.name + '_ints')

        if name.startswith('is_'):
            return self.__class__.__name__.lower() == name[3:]

        raise AttributeError(self.__class__.__name__ + '.' + name)

    def get_tracking_by_instance(self, instance, action, last_only=True):
        query = self.session.query(Tracking).filter_by(fk_id=instance.id, action=action).order_by(Tracking.when.desc())
        return query.first() if last_only else query.all()

    def apply(self, params, *, bools=(), checkgroups=(), restricted=True, ignore_csrf=True):
        """
        Args:
            restricted (bool): if true, restrict any changes only to fields which we allow attendees to set on their own
                if false, allow changes to any fields.
        """
        bools = self.regform_bools if restricted else bools
        checkgroups = self.regform_checkgroups if restricted else checkgroups
        for column in self.__table__.columns:
            if (not restricted or column.name in self.unrestricted) and column.name in params and column.name != 'id':
                if isinstance(params[column.name], list):
                    value = ','.join(map(str, params[column.name]))
                elif isinstance(params[column.name], bool):
                    value = params[column.name]
                else:
                    value = str(params[column.name]).strip()

                try:
                    if isinstance(column.type, Float):
                        value = float(value)
                    elif isinstance(column.type, Choice) and value == '':
                        value = None
                    elif isinstance(column.type, (Choice, Integer)):
                        value = int(float(value))
                    elif isinstance(column.type, UTCDateTime):
                        value = c.EVENT_TIMEZONE.localize(datetime.strptime(value, c.TIMESTAMP_FORMAT))
                    elif isinstance(column.type, Date):
                        value = datetime.strptime(value, c.DATE_FORMAT).date()
                except:
                    pass

                setattr(self, column.name, value)

        if cherrypy.request.method.upper() == 'POST':
            for column in self.__table__.columns:
                if column.name in bools:
                    setattr(self, column.name, column.name in params and bool(int(params[column.name])))
                elif column.name in checkgroups and column.name not in params:
                    setattr(self, column.name, '')

            if not ignore_csrf:
                check_csrf(params.get('csrf_token'))


class TakesPaymentMixin(object):
    @property
    def payment_deadline(self):
        return min(c.UBER_TAKEDOWN - timedelta(days=2),
                   datetime.combine((self.registered + timedelta(days=14)).date(), time(23, 59)))


class Session(SessionManager):
    engine = sqlalchemy.create_engine(c.SQLALCHEMY_URL, pool_size=50, max_overflow=100)

    @classmethod
    def initialize_db(cls, modify_tables=False, drop=False):
        """
        Initialize the database and optionally create/drop tables

        Initializes the database connection for use, and attempt to create any
        tables registered in our metadata which do not actually exist yet in the
        database.

        This calls the underlying sideboard function, HOWEVER, in order to actually create
        any tables, you must specify modify_tables=True.  The reason is, we need to wait for
        all models from all plugins to insert their mixin data, so we wait until one spot
        in order to create the database tables.

        Any calls to initialize_db() that do not specify modify_tables=True are ignored.
        i.e. anywhere in Sideboard that calls initialize_db() will be ignored
        i.e. ubersystem is forcing all calls that don't specify modify_tables=True to be ignored

        Keyword Arguments:
        modify_tables -- If False, this function does nothing.
        drop -- USE WITH CAUTION: If True, then we will drop any tables in the database
        """
        if modify_tables:
            super(Session, cls).initialize_db(drop=drop)

    class QuerySubclass(Query):
        @property
        def is_single_table_query(self):
            return len(self.column_descriptions) == 1

        @property
        def model(self):
            assert self.is_single_table_query, 'actions such as .order() and .icontains() and .iexact() are only valid for single-table queries'
            return self.column_descriptions[0]['type']

        def order(self, attrs):
            order = []
            for attr in listify(attrs):
                col = getattr(self.model, attr.lstrip('-'))
                order.append(col.desc() if attr.startswith('-') else col)
            return self.order_by(*order)

        def icontains(self, attr=None, val=None, **filters):
            query = self
            if len(self.column_descriptions) == 1 and filters:
                for colname, val in filters.items():
                    query = query.filter(getattr(self.model, colname).ilike('%{}%'.format(val)))
            if attr and val:
                query = self.filter(attr.ilike('%{}%'.format(val)))
            return query

        def iexact(self, **filters):
            return self.filter(*[func.lower(getattr(self.model, attr)) == func.lower(val) for attr, val in filters.items()])

    class SessionMixin:
        def admin_attendee(self):
            return self.admin_account(cherrypy.session['account_id']).attendee

        def logged_in_volunteer(self):
            return self.attendee(cherrypy.session['staffer_id'])

        def checklist_status(self, slug, department):
            attendee = self.admin_attendee()
            conf = DeptChecklistConf.instances[slug]
            return {
                'conf': conf,
                'relevant': attendee.is_single_dept_head and attendee.assigned_depts_ints == [int(department or 0)],
                'completed': conf.completed(attendee)
            }

        def jobs_for_signups(self):
            fields = ['name', 'location_label', 'description', 'weight', 'start_time_local', 'duration', 'weighted_hours', 'restricted', 'extra15', 'taken']
            jobs = self.logged_in_volunteer().possible_and_current
            restricted_hours = set()
            for job in jobs:
                if job.restricted:
                    restricted_hours.add(frozenset(job.hours))
            return [job.to_dict(fields) for job in jobs if job.restricted or frozenset(job.hours) not in restricted_hours]

        def guess_attendee_watchentry(self, attendee):
            return self.query(WatchList).filter(and_(or_(WatchList.first_names.contains(attendee.first_name),
                                                         WatchList.email == attendee.email,
                                                         WatchList.birthdate == attendee.birthdate),
                                                     WatchList.last_name == attendee.last_name,
                                                     WatchList.active == True)).all()

        def get_account_by_email(self, email):
            return self.query(AdminAccount).join(Attendee).filter(func.lower(Attendee.email) == func.lower(email)).one()

        def no_email(self, subject):
            return not self.query(Email).filter_by(subject=subject).all()

        def lookup_attendee(self, full_name, email, zip_code):
            words = full_name.split()
            for i in range(1, len(words)):
                first, last = ' '.join(words[:i]), ' '.join(words[i:])
                attendee = self.query(Attendee).iexact(first_name=first, last_name=last, email=email, zip_code=zip_code).all()
                if attendee:
                    return attendee[0]
            raise ValueError('attendee not found')

        def next_badge_num(self, badge_type, old_badge_num):
            # assert_badge_locked()
            badge_type = int(badge_type)

            if badge_type not in c.PREASSIGNED_BADGE_TYPES:
                return 0

            sametype = self.query(Attendee).filter(Attendee.badge_type == badge_type,
                                                   Attendee.badge_num >= c.BADGE_RANGES[badge_type][0],
                                                   Attendee.badge_num <= c.BADGE_RANGES[badge_type][1])
            if sametype.count():
                next = sametype.order_by(Attendee.badge_num.desc()).first().badge_num
                if old_badge_num and next == old_badge_num:
                    next = next  # Prevents incrementing if the current badge already has the highest badge number in the range.
                else:
                    next += 1
            else:
                next = c.BADGE_RANGES[badge_type][0]

            # Adjusts the badge number based on badges in the session
            for attendee in [m for m in chain(self.new, self.dirty) if isinstance(m, Attendee)]:
                if attendee.badge_type == badge_type and attendee.badge_num <= c.BADGE_RANGES[badge_type][1]:
                    next = max(next, 1 + attendee.badge_num)

            return next

        def shift_badges(self, badge_type, badge_num, *, until=None, **direction):
            # assert_badge_locked()
            until = until or c.MAX_BADGE
            assert c.SHIFT_CUSTOM_BADGES
            assert not any(param for param in direction if param not in ['up', 'down']), 'unknown parameters'
            assert len(direction) < 2, 'you cannot specify both up and down parameters'
            down = (not direction['up']) if 'up' in direction else direction.get('down', True)
            shift = -1 if down else 1
            for a in self.query(Attendee).filter(Attendee.badge_type == badge_type,
                                                 Attendee.badge_num >= badge_num,
                                                 Attendee.badge_num <= until,
                                                 Attendee.badge_num != 0):
                a.badge_num += shift

        def change_badge(self, attendee, badge_type, badge_num=None):
            """
            Badges should always be assigned a number if they're marked as
            pre-assigned or if they've been checked in.  If auto-shifting is
            also turned off, badge numbers cannot clobber other numbers,
            otherwise we'll shift all the other badge numbers around the old
            and new numbers.
            """
            # assert_badge_locked()
            from uber.badge_funcs import check_range
            badge_type = int(badge_type)
            old_badge_type, old_badge_num = attendee.badge_type, attendee.badge_num

            out_of_range = check_range(badge_num, badge_type)
            next = self.next_badge_num(badge_type, old_badge_num)
            if out_of_range:
                return out_of_range
            elif not badge_num and next > c.BADGE_RANGES[badge_type][1]:
                return 'There are no more badges available for that type'
            elif badge_type in c.PREASSIGNED_BADGE_TYPES and c.AFTER_PRINTED_BADGE_DEADLINE:
                return 'Custom badges have already been ordered'

            if not c.SHIFT_CUSTOM_BADGES:
                badge_num = badge_num or next
                if badge_num != 0:
                    existing = self.query(Attendee).filter_by(badge_type=badge_type, badge_num=badge_num) \
                                                   .filter(Attendee.id != attendee.id)
                    if existing.count():
                        return 'That badge number already belongs to {!r}'.format(existing.first().full_name)
            else:
                # fill in the gap from the old number, if applicable
                if old_badge_num:
                    self.shift_badges(old_badge_type, old_badge_num + 1, down=True)

                # determine the new badge number now that the badges have shifted
                next = self.next_badge_num(badge_type, old_badge_num)
                badge_num = min(int(badge_num) or next, next)

                # make room for the new number, if applicable
                if badge_num:
                    offset = 1 if badge_type == old_badge_type and old_badge_num and badge_num > old_badge_num else 0
                    self.shift_badges(badge_type, badge_num + offset, up=True)

            attendee.badge_num = badge_num
            attendee.badge_type = badge_type
            return 'Badge updated'

        def valid_attendees(self):
            return self.query(Attendee).filter(Attendee.badge_status != c.INVALID_STATUS)

        def staffers(self, only_staffing=True):
            """
            Returns a Query of attendees with efficient loading for groups and
            shifts/jobs.  By default we only return attendees where "staffing"
            is true, because before the event people can't sign up for shifts
            unless they're marked as volunteers.  However, on-site we relax that
            restriction, so we'll get attendees with shifts who are not actually
            marked as staffing.  We therefore have an optional parameter for
            clients to indicate that all attendees should be returned.
            """
            return (self.query(Attendee)
                        .filter(Attendee.badge_status.in_([c.NEW_STATUS, c.COMPLETED_STATUS]),
                                *[Attendee.staffing == True] if only_staffing else [])
                        .options(subqueryload(Attendee.group), subqueryload(Attendee.shifts).subqueryload(Shift.job))
                        .order_by(Attendee.full_name))

        def jobs(self, location=None):
            return (self.query(Job)
                        .filter_by(**{'location': location} if location else {})
                        .order_by(Job.start_time, Job.name)
                        .options(subqueryload(Job.shifts).subqueryload(Shift.attendee).subqueryload(Attendee.group)))

        def staffers_for_dropdown(self):
            return [{
                'id': id,
                'full_name': full_name.title()
            } for id, full_name in self.query(Attendee.id, Attendee.full_name)
                                       .filter_by(staffing=True)
                                       .order_by(Attendee.full_name)]

        def single_dept_heads(self, dept=None):
            assigned = {'assigned_depts': str(dept)} if dept else {}
            return (self.query(Attendee)
                        .filter_by(ribbon=c.DEPT_HEAD_RIBBON, **assigned)
                        .order_by(Attendee.full_name).all())

        def match_to_group(self, attendee, group):
            with c.BADGE_LOCK:
                available = [a for a in group.attendees if a.is_unassigned]
                matching = [a for a in available if a.badge_type == attendee.badge_type]
                if not available:
                    return 'The last badge for that group has already been assigned by another station'
                elif not matching:
                    return 'Badge #{} is a {} badge, but {} has no badges of that type'.format(attendee.badge_num, attendee.badge_type_label, group.name)
                else:
                    for attr in ['group', 'group_id', 'paid', 'amount_paid', 'ribbon']:
                        setattr(attendee, attr, getattr(matching[0], attr))
                    self.delete(matching[0])
                    self.add(attendee)
                    self.commit()

        def search(self, text, *filters):
            attendees = self.query(Attendee).outerjoin(Attendee.group).options(joinedload(Attendee.group)).filter(*filters)
            if ':' in text:
                target, term = text.split(':', 1)
                if target == 'email':
                    return attendees.icontains(Attendee.email, term.strip())
                elif target == 'group':
                    return attendees.icontains(Group.name, term.strip())

            terms = text.split()
            if len(terms) == 2:
                first, last = terms
                if first.endswith(','):
                    last, first = first.strip(','), last
                return attendees.icontains(first_name=first, last_name=last)
            elif len(terms) == 1 and terms[0].endswith(','):
                return attendees.icontains(last_name=terms[0].rstrip(','))
            elif len(terms) == 1 and terms[0].isdigit():
                return attendees.filter(Attendee.badge_num == terms[0])
            elif len(terms) == 1 and re.match('[a-z0-9]{8}-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}', terms[0]):
                return attendees.filter(or_(Attendee.id == terms[0], Group.id == terms[0]))
            else:
                checks = [Group.name.ilike('%' + text + '%')]
                for attr in ['first_name', 'last_name', 'badge_printed_name', 'email', 'comments', 'admin_notes', 'for_review']:
                    checks.append(getattr(Attendee, attr).ilike('%' + text + '%'))
                return attendees.filter(or_(*checks))

        def delete_from_group(self, attendee, group):
            """
            Sometimes we want to delete an attendee badge which is part of a group.  In most cases, we could just
            say "session.delete(attendee)" but sometimes we need to make sure that the attendee is ALSO removed
            from the "group.attendees" list before we commit, since the number of attendees in a group is used in
            our presave_adjustments() code to update the group price.  So anytime we delete an attendee in a group,
            we should use this method.
            """
            self.delete(attendee)
            group.attendees.remove(attendee)

        def assign_badges(self, group, new_badge_count, new_badge_type=c.ATTENDEE_BADGE, new_ribbon_type=None, paid=c.PAID_BY_GROUP, **extra_create_args):
            diff = int(new_badge_count) - group.badges
            sorted_unassigned = sorted(group.floating, key=lambda a: a.registered, reverse=True)

            ribbon_to_use = new_ribbon_type or group.new_ribbon

            if int(new_badge_type) in c.PREASSIGNED_BADGE_TYPES and c.AFTER_PRINTED_BADGE_DEADLINE:
                return 'Custom badges have already been ordered, so you will need to select a different badge type'
            elif diff > 0:
                for i in range(diff):
                    group.attendees.append(Attendee(badge_type=new_badge_type, ribbon=ribbon_to_use, paid=paid, **extra_create_args))
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

            if job.restricted and not attendee.trusted_in(job.location):
                return 'You cannot assign an attendee who is not trusted in this department to a restricted shift'

            if job.slots <= len(job.shifts):
                return 'All slots for this job have already been filled'

            if not job.no_overlap(attendee):
                return 'This volunteer is already signed up for a shift during that time'

            self.add(Shift(attendee=attendee, job=job))
            self.commit()

        def affiliates(self):
            amounts = defaultdict(int, {a: -i for i, a in enumerate(c.DEFAULT_AFFILIATES)})
            for aff, amt in self.query(Attendee.affiliate, Attendee.amount_extra) \
                                .filter(and_(Attendee.amount_extra > 0, Attendee.affiliate != '')):
                amounts[aff] += amt
            return [{
                'id': aff,
                'text': aff,
                'total': max(0, amt)
            } for aff, amt in sorted(amounts.items(), key=lambda tup: -tup[1])]

        def insert_test_admin_account(self):
            """
            insert a test admin into the database with username "magfest@example.com" password "magfest"
            this is ONLY allowed if no other admins already exist in the database.
            :return: True if success, False if failure
            """
            if self.query(sa.AdminAccount).count() != 0:
                return False

            attendee = sa.Attendee(
                placeholder=True,
                first_name='Test',
                last_name='Developer',
                email='magfest@example.com',
                badge_type=c.ATTENDEE_BADGE,
            )
            self.add(attendee)

            self.add(sa.AdminAccount(
                attendee=attendee,
                access=','.join(str(level) for level, name in c.ACCESS_OPTS),
                hashed=bcrypt.hashpw('magfest', bcrypt.gensalt())
            ))

            return True

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
                if hasattr('target', '__table__') and name in target.__table__.c:
                    attr.key = attr.key or name
                    attr.name = attr.name or name
                    attr.table = target.__table__
                    target.__table__.c.replace(attr)
                else:
                    setattr(target, name, attr)
        return target


class Group(MagModel, TakesPaymentMixin):
    name          = Column(UnicodeText)
    tables        = Column(Float, default=0)
    address       = Column(UnicodeText)
    website       = Column(UnicodeText)
    wares         = Column(UnicodeText)
    description   = Column(UnicodeText)
    special_needs = Column(UnicodeText)
    amount_paid   = Column(Integer, default=0, admin_only=True)
    cost          = Column(Integer, default=0, admin_only=True)
    auto_recalc   = Column(Boolean, default=True, admin_only=True)
    can_add       = Column(Boolean, default=False, admin_only=True)
    admin_notes   = Column(UnicodeText, admin_only=True)
    status        = Column(Choice(c.DEALER_STATUS_OPTS), default=c.UNAPPROVED, admin_only=True)
    registered    = Column(UTCDateTime, server_default=utcnow())
    approved      = Column(UTCDateTime, nullable=True)
    leader_id     = Column(UUID, ForeignKey('attendee.id', use_alter=True, name='fk_leader'), nullable=True)
    leader        = relationship('Attendee', foreign_keys=leader_id, post_update=True, cascade='all')

    _repr_attr_names = ['name']

    @presave_adjustment
    def _cost_and_leader(self):
        assigned = [a for a in self.attendees if not a.is_unassigned]
        if len(assigned) == 1:
            [self.leader] = assigned
        if self.auto_recalc:
            self.cost = self.default_cost
        if self.status == c.APPROVED and not self.approved:
            self.approved = datetime.now(UTC)
        if self.leader and self.is_dealer:
            self.leader.ribbon = c.DEALER_RIBBON

    @property
    def sorted_attendees(self):
        self.attendees.sort(key=lambda a: (a.is_unassigned, a.id != self.leader_id, a.full_name))
        return self.attendees

    @property
    def unassigned(self):
        """
        Returns a list of the unassigned badges for this group, sorted so that
        the paid-by-group badges come last, because when claiming unassigned
        badges we want to claim the "weird" ones first.
        """
        return sorted([a for a in self.attendees if a.is_unassigned], key=lambda a: a.paid == c.PAID_BY_GROUP)

    @property
    def floating(self):
        """
        Returns the list of paid-by-group unassigned badges for this group. This
        is a separate property from the "Group.unassigned" property because when
        automatically adding or removing unassigned badges, we care specifically
        about paid-by-group badges rather than all unassigned badges.
        """
        return [a for a in self.attendees if a.is_unassigned and a.paid == c.PAID_BY_GROUP]

    @property
    def new_ribbon(self):
        return c.DEALER_RIBBON if self.is_dealer else c.NO_RIBBON

    @property
    def ribbon_and_or_badge(self):
        badge_being_claimed = self.unassigned[0]
        if badge_being_claimed.ribbon != c.NO_RIBBON and badge_being_claimed.badge_type != c.ATTENDEE_BADGE:
            return badge_being_claimed.badge_type_label + " / " + self.ribbon_label
        elif badge_being_claimed.ribbon != c.NO_RIBBON:
            return badge_being_claimed.ribbon_label
        else:
            return badge_being_claimed.badge_type_label

    @property
    def is_dealer(self):
        return bool(self.tables and (not self.registered or self.amount_paid or self.cost))

    @property
    def is_unpaid(self):
        return self.cost > 0 and self.amount_paid == 0

    @property
    def email(self):
        if self.leader and self.leader.email:
            return self.leader.email
        elif self.leader_id:  # unattached groups
            [leader] = [a for a in self.attendees if a.id == self.leader_id]
            return leader.email
        else:
            emails = [a.email for a in self.attendees if a.email]
            if len(emails) == 1:
                return emails[0]

    @property
    def badges_purchased(self):
        return len([a for a in self.attendees if a.paid == c.PAID_BY_GROUP])

    @property
    def badges(self):
        return len(self.attendees)

    @property
    def unregistered_badges(self):
        return len([a for a in self.attendees if a.is_unassigned])

    @cost_property
    def table_cost(self):
        return sum(c.TABLE_PRICES[i] for i in range(1, 1 + int(self.tables)))

    @property
    def new_badge_cost(self):
        return c.DEALER_BADGE_PRICE if self.tables else c.get_group_price(sa.localized_now())

    @cost_property
    def badge_cost(self):
        total = 0
        for attendee in self.attendees:
            if attendee.paid == c.PAID_BY_GROUP:
                total += c.DEALER_BADGE_PRICE if attendee.is_dealer else c.get_group_price(attendee.registered)
        return total

    @cost_property
    def amount_extra(self):
        if self.is_new:
            return sum(a.amount_unpaid for a in self.attendees if a.paid == c.PAID_BY_GROUP)
        else:
            return 0

    @property
    def amount_unpaid(self):
        if self.registered:
            return max(0, self.cost - self.amount_paid)
        else:
            return self.default_cost

    @property
    def dealer_max_badges(self):
        return math.ceil(self.tables) + 1

    @property
    def dealer_badges_remaining(self):
        return self.dealer_max_badges - self.badges

    @property
    def min_badges_addable(self):
        if self.can_add:
            return 1
        elif self.is_dealer:
            return 0
        else:
            return c.MIN_GROUP_ADDITION


class Attendee(MagModel, TakesPaymentMixin):
    watchlist_id = Column(UUID, ForeignKey('watch_list.id', ondelete='set null'), nullable=True, default=None)

    group_id = Column(UUID, ForeignKey('group.id', ondelete='SET NULL'), nullable=True)
    group = relationship(Group, backref='attendees', foreign_keys=group_id, cascade='save-update,merge,refresh-expire,expunge')

    placeholder   = Column(Boolean, default=False, admin_only=True)
    first_name    = Column(UnicodeText)
    last_name     = Column(UnicodeText)
    email         = Column(UnicodeText)
    birthdate     = Column(Date, nullable=True, default=None)
    age_group     = Column(Choice(c.AGE_GROUPS), default=c.AGE_UNKNOWN, nullable=True)

    international = Column(Boolean, default=False)
    zip_code      = Column(UnicodeText)
    address1      = Column(UnicodeText)
    address2      = Column(UnicodeText)
    city          = Column(UnicodeText)
    region        = Column(UnicodeText)
    country       = Column(UnicodeText)
    no_cellphone  = Column(Boolean, default=False)
    ec_phone      = Column(UnicodeText)
    cellphone     = Column(UnicodeText)

    interests   = Column(MultiChoice(c.INTEREST_OPTS))
    found_how   = Column(UnicodeText)
    comments    = Column(UnicodeText)
    for_review  = Column(UnicodeText, admin_only=True)
    admin_notes = Column(UnicodeText, admin_only=True)

    badge_num    = Column(Integer, default=0, nullable=True, admin_only=True)
    badge_type   = Column(Choice(c.BADGE_OPTS), default=c.ATTENDEE_BADGE)
    badge_status = Column(Choice(c.BADGE_STATUS_OPTS), default=c.NEW_STATUS, admin_only=True)
    ribbon       = Column(Choice(c.RIBBON_OPTS), default=c.NO_RIBBON, admin_only=True)

    affiliate    = Column(UnicodeText)
    shirt        = Column(Choice(c.SHIRT_OPTS), default=c.NO_SHIRT)
    can_spam     = Column(Boolean, default=False)
    regdesk_info = Column(UnicodeText, admin_only=True)
    extra_merch  = Column(UnicodeText, admin_only=True)
    got_merch    = Column(Boolean, default=False, admin_only=True)

    reg_station   = Column(Integer, nullable=True, admin_only=True)
    registered = Column(UTCDateTime, server_default=utcnow())
    checked_in = Column(UTCDateTime, nullable=True)

    paid             = Column(Choice(c.PAYMENT_OPTS), default=c.NOT_PAID, admin_only=True)
    overridden_price = Column(Integer, nullable=True, admin_only=True)
    amount_paid      = Column(Integer, default=0, admin_only=True)
    amount_extra     = Column(Choice(c.DONATION_TIER_OPTS, allow_unspecified=True), default=0)
    amount_refunded  = Column(Integer, default=0, admin_only=True)
    payment_method   = Column(Choice(c.PAYMENT_METHOD_OPTS), nullable=True)

    badge_printed_name = Column(UnicodeText)

    staffing          = Column(Boolean, default=False)
    requested_depts   = Column(MultiChoice(c.JOB_INTEREST_OPTS))
    assigned_depts    = Column(MultiChoice(c.JOB_LOCATION_OPTS), admin_only=True)
    trusted_depts     = Column(MultiChoice(c.JOB_LOCATION_OPTS), admin_only=True)
    nonshift_hours    = Column(Integer, default=0, admin_only=True)
    past_years        = Column(UnicodeText, admin_only=True)
    can_work_setup    = Column(Boolean, default=False, admin_only=True)
    can_work_teardown = Column(Boolean, default=False, admin_only=True)

    no_shirt          = relationship('NoShirt', backref=backref('attendee', load_on_pending=True), uselist=False)
    admin_account     = relationship('AdminAccount', backref=backref('attendee', load_on_pending=True), uselist=False)
    food_restrictions = relationship('FoodRestrictions', backref=backref('attendee', load_on_pending=True), uselist=False)

    shifts = relationship('Shift', backref='attendee')
    sales = relationship('Sale', backref='attendee', cascade='save-update,merge,refresh-expire,expunge')
    mpoints_for_cash = relationship('MPointsForCash', backref='attendee')
    old_mpoint_exchanges = relationship('OldMPointExchange', backref='attendee')
    dept_checklist_items = relationship('DeptChecklistItem', backref='attendee')

    _repr_attr_names = ['full_name']

    @predelete_adjustment
    def _shift_badges(self):
        # _assert_badge_lock()
        if self.has_personalized_badge and c.SHIFT_CUSTOM_BADGES:
            self.session.shift_badges(self.badge_type, self.badge_num, down=True)

    @presave_adjustment
    def _misc_adjustments(self):
        if not self.amount_extra:
            self.affiliate = ''

        if self.birthdate == '':
            self.birthdate = None

        if not self.shirt_eligible:
            self.shirt = c.NO_SHIRT

        if self.paid != c.REFUNDED:
            self.amount_refunded = 0

        if c.AT_THE_CON and self.badge_num and (self.is_new or self.badge_type not in c.PREASSIGNED_BADGE_TYPES):
            self.checked_in = datetime.now(UTC)

        if self.birthdate:
            self.age_group = self.age_group_conf['val']

        for attr in ['first_name', 'last_name']:
            value = getattr(self, attr)
            if value.isupper() or value.islower():
                setattr(self, attr, value.title())

    @presave_adjustment
    def _badge_adjustments(self):
        # _assert_badge_lock()

        if self.badge_type in [c.PSEUDO_GROUP_BADGE, c.PSEUDO_DEALER_BADGE]:
            if self.is_dealer:
                self.ribbon = c.DEALER_RIBBON
            self.badge_type = c.ATTENDEE_BADGE

        if c.PRE_CON:
            if self.paid == c.NOT_PAID or not self.has_personalized_badge or self.is_unassigned:
                self.badge_num = 0
            elif self.has_personalized_badge and not self.badge_num:
                if self.paid != c.NOT_PAID:
                    self.badge_num = self.session.next_badge_num(self.badge_type, old_badge_num=0)

    @presave_adjustment
    def _status_adjustments(self):
        if self.badge_status == c.NEW_STATUS and self.banned:
            self.badge_status = c.DEFERRED_STATUS
            try:
                send_email(c.SECURITY_EMAIL, [c.REGDESK_EMAIL, c.SECURITY_EMAIL], 'Banned attendee registration',
                           render('emails/reg_workflow/banned_attendee.txt', {'attendee': self}), model='n/a')
            except:
                log.error('unable to send banned email about {}', self)
        elif self.badge_status == c.NEW_STATUS and not self.placeholder and self.first_name \
                and (self.paid in [c.HAS_PAID, c.NEED_NOT_PAY]
                     or self.paid == c.PAID_BY_GROUP and self.group_id and not self.group.amount_unpaid):
            self.badge_status = c.COMPLETED_STATUS

    @presave_adjustment
    def _staffing_adjustments(self):
        if self.ribbon == c.DEPT_HEAD_RIBBON:
            self.staffing = True
            self.trusted_depts = self.assigned_depts
            if c.SHIFT_CUSTOM_BADGES or c.STAFF_BADGE not in c.PREASSIGNED_BADGE_TYPES:
                self.badge_type = c.STAFF_BADGE
            if self.paid == c.NOT_PAID:
                self.paid = c.NEED_NOT_PAY
        elif self.ribbon == c.VOLUNTEER_RIBBON and self.is_new:
            self.staffing = True

        if not self.is_new:
            old_ribbon = self.orig_value_of('ribbon')
            old_staffing = self.orig_value_of('staffing')
            if self.staffing and not old_staffing or self.ribbon == c.VOLUNTEER_RIBBON and old_ribbon != c.VOLUNTEER_RIBBON:
                self.staffing = True
            elif old_staffing and not self.staffing or self.ribbon != c.VOLUNTEER_RIBBON and old_ribbon == c.VOLUNTEER_RIBBON:
                self.unset_volunteering()

        if self.badge_type == c.STAFF_BADGE and self.ribbon == c.VOLUNTEER_RIBBON:
            self.ribbon = c.NO_RIBBON
        elif self.staffing and self.badge_type != c.STAFF_BADGE and self.ribbon == c.NO_RIBBON:
            self.ribbon = c.VOLUNTEER_RIBBON

        if self.badge_type == c.STAFF_BADGE:
            self.staffing = True

        # remove trusted status from any dept we are not assigned to
        self.trusted_depts = ','.join(str(td) for td in self.trusted_depts_ints if td in self.assigned_depts_ints)

    def unset_volunteering(self):
        self.staffing = False
        self.trusted_depts = self.requested_depts = self.assigned_depts = ''
        if self.ribbon == c.VOLUNTEER_RIBBON:
            self.ribbon = c.NO_RIBBON
        if self.badge_type == c.STAFF_BADGE:
            if c.SHIFT_CUSTOM_BADGES:
                self.session.shift_badges(c.STAFF_BADGE, self.badge_num, down=True)
            self.badge_type = c.ATTENDEE_BADGE
        del self.shifts[:]

    @property
    def ribbon_and_or_badge(self):
        if self.ribbon != c.NO_RIBBON and self.badge_type != c.ATTENDEE_BADGE:
            return self.badge_type_label + " / " + self.ribbon_label
        elif self.ribbon != c.NO_RIBBON:
            return self.ribbon_label
        else:
            return self.badge_type_label

    @cost_property
    def badge_cost(self):
        registered = self.registered_local if self.registered else sa.localized_now()
        if self.paid in [c.PAID_BY_GROUP, c.NEED_NOT_PAY]:
            return 0
        elif self.overridden_price is not None:
            return self.overridden_price
        elif self.badge_type == c.ONE_DAY_BADGE:
            return c.get_oneday_price(registered)
        elif self.is_presold_oneday:
            return c.get_presold_oneday_price(self.badge_type)
        else:
            return c.get_attendee_price(registered)

    @cost_property
    def discount(self):
        return -self.age_group_conf['discount']

    @property
    def age_group_conf(self):
        if self.birthdate:
            day = c.EPOCH.date() if date.today() <= c.EPOCH.date() else sa.localized_now().date()
            attendee_age = (day - self.birthdate).days // 365.2425
            for val, age_group in c.AGE_GROUP_CONFIGS.items():
                if val != c.AGE_UNKNOWN and age_group['min_age'] <= attendee_age <= age_group['max_age']:
                    return age_group

        return c.AGE_GROUP_CONFIGS[int(self.age_group or c.AGE_UNKNOWN)]

    @property
    def total_cost(self):
        return self.default_cost + self.amount_extra

    @property
    def amount_unpaid(self):
        return max(0, self.total_cost - self.amount_paid)

    @property
    def is_unpaid(self):
        return self.paid == c.NOT_PAID

    @property
    def is_unassigned(self):
        return not self.first_name

    @property
    def is_dealer(self):
        return self.ribbon == c.DEALER_RIBBON or self.badge_type == c.PSEUDO_DEALER_BADGE

    @property
    def is_dept_head(self):
        return self.ribbon == c.DEPT_HEAD_RIBBON

    @property
    def is_presold_oneday(self):
        """
        Returns a boolean indicating whether this is a c.FRIDAY/c.SATURDAY/etc
        badge; see the presell_one_days config option for a full explanation.
        """
        return self.badge_type_label in c.DAYS_OF_WEEK

    @property
    def can_check_in(self):
        valid = self.paid != c.NOT_PAID and self.badge_status in [c.NEW_STATUS, c.COMPLETED_STATUS] and not self.is_unassigned
        if valid and self.is_presold_oneday:
            valid = self.badge_type_label == localized_now().strftime('%A')
        return valid

    @property
    def shirt_size_marked(self):
        return self.shirt not in [c.NO_SHIRT, c.SIZE_UNKNOWN]

    @property
    def is_group_leader(self):
        return self.group and self.id == self.group.leader_id

    @property
    def unassigned_name(self):
        if self.group_id and self.is_unassigned:
            return '[Unassigned {self.badge}]'.format(self=self)

    @hybrid_property
    def full_name(self):
        return self.unassigned_name or '{self.first_name} {self.last_name}'.format(self=self)

    @full_name.expression
    def full_name(cls):
        return case([
            (or_(cls.first_name == None, cls.first_name == ''), 'zzz')
        ], else_=func.lower(cls.first_name + ' ' + cls.last_name))

    @hybrid_property
    def last_first(self):
        return self.unassigned_name or '{self.last_name}, {self.first_name}'.format(self=self)

    @last_first.expression
    def last_first(cls):
        return case([
            (or_(cls.first_name == None, cls.first_name == ''), 'zzz')
        ], else_=func.lower(cls.last_name + ', ' + cls.first_name))

    @hybrid_property
    def last_first(self):
        return self.unassigned_name or '{self.last_name}, {self.first_name}'.format(self=self)

    @last_first.expression
    def last_first(cls):
        return case([
            (or_(cls.first_name == None, cls.first_name == ''), 'zzz')
        ], else_=func.lower(cls.last_name + ', ' + cls.first_name))

    @property
    def watchlist_guess(self):
        try:
            with Session() as session:
                return [w.to_dict() for w in session.guess_attendee_watchentry(self)]
        except:
            return None

    @property
    def banned(self):
        return listify(self.watch_list or self.watchlist_guess)

    @property
    def badge(self):
        if self.paid == c.NOT_PAID:
            badge = 'Unpaid ' + self.badge_type_label
        elif self.badge_num:
            badge = '{} #{}'.format(self.badge_type_label, self.badge_num)
        else:
            badge = self.badge_type_label

        if self.ribbon != c.NO_RIBBON:
            badge += ' ({})'.format(self.ribbon_label)

        return badge

    @property
    def is_transferable(self):
        return not self.is_new and not self.trusted_somewhere and not self.checked_in \
           and self.paid in [c.HAS_PAID, c.PAID_BY_GROUP] \
           and self.badge_type in c.TRANSFERABLE_BADGE_TYPES \
           and not self.admin_account

    @property
    def gets_free_shirt(self):
        return self.is_dept_head \
            or self.badge_type == c.STAFF_BADGE \
            or self.staffing and (self.assigned_depts and not self.takes_shifts or self.weighted_hours >= 6)

    @property
    def gets_paid_shirt(self):
        return self.amount_extra >= c.SHIRT_LEVEL

    @property
    def gets_shirt(self):
        return self.gets_paid_shirt or self.gets_free_shirt

    @property
    def shirt_eligible(self):
        return self.gets_shirt or self.staffing

    @property
    def has_personalized_badge(self):
        return self.badge_type in c.PREASSIGNED_BADGE_TYPES

    @property
    def donation_swag(self):
        extra = self.amount_extra
        return [desc for amount, desc in sorted(c.DONATION_TIERS.items()) if amount and extra >= amount]

    @property
    def merch(self):
        merch = self.donation_swag
        if self.gets_shirt and c.DONATION_TIERS[c.SHIRT_LEVEL] not in merch:
            merch.append(c.DONATION_TIERS[c.SHIRT_LEVEL])
        elif self.gets_free_shirt:
            shirt = '2nd ' + c.DONATION_TIERS[c.SHIRT_LEVEL]
            if self.takes_shifts and self.worked_hours < 6:
                shirt += ' (tell them they will be reported if they take their shirt then do not work their shifts)'
            merch.append(shirt)
        if self.extra_merch:
            merch.append(self.extra_merch)
        return comma_and(merch)

    @property
    def accoutrements(self):
        stuff = [] if self.ribbon == c.NO_RIBBON else ['a ' + self.ribbon_label + ' ribbon']
        if c.WRISTBANDS_ENABLED:
            stuff.append('a {} wristband'.format(c.WRISTBAND_COLORS[self.age_group]))
        if self.regdesk_info:
            stuff.append(self.regdesk_info)
        if self.amount_extra >= c.SUPPORTER_LEVEL:
            stuff.append('their Supporter badge')
        return (' with ' if stuff else '') + comma_and(stuff)

    @property
    def is_single_dept_head(self):
        return self.is_dept_head and len(self.assigned_depts_ints) == 1

    @property
    def multiply_assigned(self):
        return len(self.assigned_depts_ints) > 1

    @property
    def takes_shifts(self):
        return bool(self.staffing and set(self.assigned_depts_ints) - set(c.SHIFTLESS_DEPTS))

    @property
    def hours(self):
        all_hours = set()
        for shift in self.shifts:
            all_hours.update(shift.job.hours)
        return all_hours

    @property
    def hour_map(self):
        all_hours = {}
        for shift in self.shifts:
            for hour in shift.job.hours:
                all_hours[hour] = shift.job
        return all_hours

    @cached_property
    def possible(self):
        assert self.session, '.possible property may only be accessed for jobs attached to a session'
        if not self.assigned_depts and not c.AT_THE_CON:
            return []
        else:
            return [job for job in self.session.query(Job)
                                       .filter(*[] if c.AT_THE_CON else [Job.location.in_(self.assigned_depts_ints)])
                                       .options(joinedload(Job.shifts))
                                       .order_by(Job.start_time).all()
                        if job.slots > len(job.shifts)
                           and job.no_overlap(self)
                           and (job.type != c.SETUP or self.can_work_setup)
                           and (job.type != c.TEARDOWN or self.can_work_teardown)
                           and (not job.restricted or self.trusted_in(job.location))]

    @property
    def possible_opts(self):
        return [(job.id, '(%s) [%s] %s' % (hour_day_format(job.start_time), job.location_label, job.name))
                for job in self.possible if sa.localized_now() < job.start_time]

    @property
    def possible_and_current(self):
        jobs = [s.job for s in self.shifts]
        for job in jobs:
            job.taken = True
        jobs.extend(self.possible)
        return sorted(jobs, key=lambda j: j.start_time)

    @property
    def worked_shifts(self):
        return [shift for shift in self.shifts if shift.worked == c.SHIFT_WORKED]

    @property
    def weighted_hours(self):
        wh = sum((shift.job.weighted_hours for shift in self.shifts), 0.0)
        return wh + self.nonshift_hours

    @property
    def worked_hours(self):
        wh = sum((shift.job.real_duration * shift.job.weight for shift in self.worked_shifts), 0.0)
        return wh + self.nonshift_hours

    def requested(self, department):
        return department in self.requested_depts_ints

    def assigned_to(self, department):
        return int(department or 0) in self.assigned_depts_ints

    def trusted_in(self, department):
        return int(department or 0) in self.trusted_depts_ints

    @property
    def trusted_somewhere(self):
        """
        :return: True if this Attendee is trusted in at least 1 department
        """
        return len(self.trusted_depts_ints) > 0

    def has_shifts_in(self, department):
        return any(shift.job.location == department for shift in self.shifts)

    @property
    def shift_prereqs_complete(self):
        return not self.placeholder and self.food_restrictions and self.shirt_size_marked

    @property
    def past_years_json(self):
        return json.loads(self.past_years or '[]')


class WatchList(MagModel):
    first_names     = Column(UnicodeText)
    last_name       = Column(UnicodeText)
    email           = Column(UnicodeText, default='')
    birthdate       = Column(Date, nullable=True, default=None)
    reason          = Column(UnicodeText)
    action          = Column(UnicodeText)
    active          = Column(Boolean, default=True)
    attendees = relationship('Attendee', backref=backref('watch_list', load_on_pending=True))

    @presave_adjustment
    def _fix_birthdate(self):
        if self.birthdate == '':
            self.birthdate = None


class AdminAccount(MagModel):
    attendee_id = Column(UUID, ForeignKey('attendee.id'), unique=True)
    hashed      = Column(UnicodeText)
    access      = Column(MultiChoice(c.ACCESS_OPTS))

    password_reset = relationship('PasswordReset', backref='admin_account', uselist=False)

    def __repr__(self):
        return '<{}>'.format(self.attendee.full_name)

    @staticmethod
    def is_nick():
        return AdminAccount.admin_name() in c.JERKS

    @staticmethod
    def admin_name():
        try:
            with Session() as session:
                return session.admin_attendee().full_name
        except:
            return None

    @staticmethod
    def admin_email():
        try:
            with Session() as session:
                return session.admin_attendee().email
        except:
            return None

    @staticmethod
    def access_set(id=None):
        try:
            with Session() as session:
                id = id or cherrypy.session['account_id']
                return set(session.admin_account(id).access_ints)
        except:
            return set()


class PasswordReset(MagModel):
    account_id = Column(UUID, ForeignKey('admin_account.id'), unique=True)
    generated  = Column(UTCDateTime, server_default=utcnow())
    hashed     = Column(UnicodeText)

    @property
    def is_expired(self):
        return self.generated < datetime.now(UTC) - timedelta(days=7)


class FoodRestrictions(MagModel):
    attendee_id   = Column(UUID, ForeignKey('attendee.id'), unique=True)
    standard      = Column(MultiChoice(c.FOOD_RESTRICTION_OPTS))
    sandwich_pref = Column(MultiChoice(c.SANDWICH_OPTS))
    freeform      = Column(UnicodeText)

    def __getattr__(self, name):
        try:
            return super(FoodRestrictions, self).__getattr__(name)
        except AttributeError:
            restriction = getattr(c, name.upper())
            if restriction not in c.FOOD_RESTRICTIONS:
                return MagModel.__getattr__(self, name)
            elif restriction == c.VEGETARIAN and c.VEGAN in self.standard_ints:
                return False
            elif restriction == c.PORK and {c.VEGETARIAN, c.VEGAN}.intersection(self.standard_ints):
                return True
            else:
                return restriction in self.standard_ints


class NoShirt(MagModel):
    attendee_id = Column(UUID, ForeignKey('attendee.id'), unique=True)


class MerchPickup(MagModel):
    picked_up_by_id  = Column(UUID, ForeignKey('attendee.id'))
    picked_up_for_id = Column(UUID, ForeignKey('attendee.id'), unique=True)
    picked_up_by     = relationship(Attendee, primaryjoin='MerchPickup.picked_up_by_id == Attendee.id', cascade='save-update,merge,refresh-expire,expunge')
    picked_up_for    = relationship(Attendee, primaryjoin='MerchPickup.picked_up_for_id == Attendee.id', cascade='save-update,merge,refresh-expire,expunge')


class DeptChecklistItem(MagModel):
    attendee_id = Column(UUID, ForeignKey('attendee.id'))
    slug        = Column(UnicodeText)
    comments    = Column(UnicodeText, default='')

    __table_args__ = (
        UniqueConstraint('attendee_id', 'slug', name='_dept_checklist_item_uniq'),
    )


class Job(MagModel):
    type        = Column(Choice(c.JOB_TYPE_OPTS), default=c.REGULAR)
    name        = Column(UnicodeText)
    description = Column(UnicodeText)
    location    = Column(Choice(c.JOB_LOCATION_OPTS))
    start_time  = Column(UTCDateTime)
    duration    = Column(Integer)
    weight      = Column(Float, default=1)
    slots       = Column(Integer)
    restricted  = Column(Boolean, default=False)
    extra15     = Column(Boolean, default=False)
    shifts      = relationship('Shift', backref='job')

    _repr_attr_names = ['name']

    @property
    def hours(self):
        hours = set()
        for i in range(self.duration):
            hours.add(self.start_time + timedelta(hours=i))
        return hours

    @property
    def end_time(self):
        return self.start_time + timedelta(hours=self.duration)

    def no_overlap(self, attendee):
        before = self.start_time - timedelta(hours=1)
        after  = self.start_time + timedelta(hours=self.duration)
        return (not self.hours.intersection(attendee.hours)
            and (before not in attendee.hour_map
                or not attendee.hour_map[before].extra15
                or self.location == attendee.hour_map[before].location)
            and (after not in attendee.hour_map
                or not self.extra15
                or self.location == attendee.hour_map[after].location))

    @property
    def slots_taken(self):
        return len(self.shifts)

    @property
    def slots_untaken(self):
        return max(0, self.slots - self.slots_taken)

    @property
    def is_setup(self):
        return self.start_time < c.EPOCH

    @property
    def is_teardown(self):
        return self.start_time >= c.ESCHATON

    @property
    def real_duration(self):
        return self.duration + (0.25 if self.extra15 else 0)

    @property
    def weighted_hours(self):
        return self.weight * self.real_duration

    @property
    def total_hours(self):
        return self.weighted_hours * self.slots

    def _potential_volunteers(self, staffing_only=False, order_by=Attendee.full_name):
        """
        return a list of attendees who:
        1) are assigned to this job's location
        2) are allowed to work this job (job is unrestricted, or they're trusted in this job's location)

        :param: staffing_only: restrict result to attendees where staffing==True
        :param: order_by: order by another Attendee attribute
        """
        return (self.session.query(Attendee)
                .filter(Attendee.assigned_depts.contains(str(self.location)))
                .filter(*[Attendee.trusted_depts.contains(str(self.location))] if self.restricted else [])
                .filter_by(**{'staffing': True} if staffing_only else {})
                .order_by(order_by)
                .all())

    @property
    def capable_volunteers_opts(self):
        # format output for use with the {% options %} template decorator
        return [(a.id, a.full_name) for a in self.capable_volunteers]

    @property
    def capable_volunteers(self):
        """
        Return a list of volunteers who could sign up for this job.

        Important: Just because a volunteer is capable of working
        this job doesn't mean they are actually available to work it.
        They may have other shift hours during that time period.
        """
        return self._potential_volunteers(staffing_only=True)

    @cached_property
    def available_volunteers(self):
        """
        Returns a list of volunteers who are allowed to sign up for
        this Job and have the free time to work it.
        """
        return [s for s in self._potential_volunteers(order_by=Attendee.last_first) if self.no_overlap(s)]


class Shift(MagModel):
    job_id      = Column(UUID, ForeignKey('job.id', ondelete='cascade'))
    attendee_id = Column(UUID, ForeignKey('attendee.id', ondelete='cascade'))
    worked      = Column(Choice(c.WORKED_STATUS_OPTS), default=c.SHIFT_UNMARKED)
    rating      = Column(Choice(c.RATING_OPTS), default=c.UNRATED)
    comment     = Column(UnicodeText)

    @property
    def name(self):
        return "{self.attendee.full_name}'s {self.job.name!r} shift".format(self=self)

    @staticmethod
    def dump(shifts):
        return {shift.id: shift.to_dict() for shift in shifts}


class MPointsForCash(MagModel):
    attendee_id = Column(UUID, ForeignKey('attendee.id'))
    amount      = Column(Integer)
    when        = Column(UTCDateTime, default=lambda: datetime.now(UTC))


class OldMPointExchange(MagModel):
    attendee_id = Column(UUID, ForeignKey('attendee.id'))
    amount      = Column(Integer)
    when        = Column(UTCDateTime, default=lambda: datetime.now(UTC))


class Sale(MagModel):
    attendee_id    = Column(UUID, ForeignKey('attendee.id', ondelete='set null'), nullable=True)
    what           = Column(UnicodeText)
    cash           = Column(Integer, default=0)
    mpoints        = Column(Integer, default=0)
    when           = Column(UTCDateTime, default=lambda: datetime.now(UTC))
    reg_station    = Column(Integer, nullable=True)
    payment_method = Column(Choice(c.SALE_OPTS), default=c.MERCH)


class ArbitraryCharge(MagModel):
    amount      = Column(Integer)
    what        = Column(UnicodeText)
    when        = Column(UTCDateTime, default=lambda: datetime.now(UTC))
    reg_station = Column(Integer, nullable=True)

    _repr_attr_names = ['what']


class ApprovedEmail(MagModel):
    subject = Column(UnicodeText)

    _repr_attr_names = ['subject']


class Email(MagModel):
    fk_id   = Column(UUID, nullable=True)
    model   = Column(UnicodeText)
    when    = Column(UTCDateTime, default=lambda: datetime.now(UTC))
    subject = Column(UnicodeText)
    dest    = Column(UnicodeText)
    body    = Column(UnicodeText)

    _repr_attr_names = ['subject']

    @cached_property
    def fk(self):
        try:
            return getattr(self.session, globals()[self.model].__tablename__)(self.fk_id)
        except:
            return None

    @property
    def rcpt_name(self):
        if self.model == 'Group':
            return self.fk.leader.full_name
        else:
            return self.fk.full_name

    @property
    def is_html(self):
        return '<body' in self.body

    @property
    def html(self):
        if self.is_html:
            return SafeString(re.split('<body[^>]*>', self.body)[1].split('</body>')[0])
        else:
            return SafeString(self.body.replace('\n', '<br/>'))


class Tracking(MagModel):
    fk_id  = Column(UUID)
    model  = Column(UnicodeText)
    when   = Column(UTCDateTime, default=lambda: datetime.now(UTC))
    who    = Column(UnicodeText)
    which  = Column(UnicodeText)
    links  = Column(UnicodeText)
    action = Column(Choice(c.TRACKING_OPTS))
    data   = Column(UnicodeText)

    @classmethod
    def format(cls, values):
        return ', '.join('{}={}'.format(k, v) for k, v in values.items())

    @classmethod
    def repr(cls, column, value):
        try:
            s = repr(value)
            if column.name == 'hashed':
                return '<bcrypted>'
            elif isinstance(column.type, MultiChoice):
                opts = dict(column.type.choices)
                return repr('' if not value else (','.join(opts[int(opt)] for opt in value.split(',') if int(opt or 0) in opts)))
            elif isinstance(column.type, Choice) and value not in [None, '']:
                return repr(dict(column.type.choices).get(int(value), '<nonstandard>'))
            else:
                return s
        except Exception as e:
            raise ValueError('error formatting {} ({!r})'.format(column.name, value)) from e

    @classmethod
    def differences(cls, instance):
        diff = {}
        for attr, column in instance.__table__.columns.items():
            new_val = getattr(instance, attr)
            old_val = instance.orig_value_of(attr)
            if old_val != new_val:
                diff[attr] = "'{} -> {}'".format(cls.repr(column, old_val), cls.repr(column, new_val))
        return diff

    # TODO: add new table for page views to eliminated track_pageview method and to eliminate Budget special case
    @classmethod
    def track(cls, action, instance):
        if action in [c.CREATED, c.UNPAID_PREREG, c.EDITED_PREREG]:
            vals = {attr: cls.repr(column, getattr(instance, attr)) for attr, column in instance.__table__.columns.items()}
            data = cls.format(vals)
        elif action == c.UPDATED:
            diff = cls.differences(instance)
            data = cls.format(diff)
            if len(diff) == 1 and 'badge_num' in diff:
                action = c.AUTO_BADGE_SHIFT
            elif not data:
                return
        elif instance == 'Budget':  # Vaguely horrifying special-casing where we make up fake data so we can insert this entry into the tracking DB
            data = 'Budget Page'
            who = AdminAccount.admin_name() or (current_thread().name if current_thread().daemon else 'non-admin')
            with Session() as session:
                session.add(Tracking(
                    model='Budget',
                    fk_id=str(uuid4()),
                    which='Budget',
                    who=who,
                    links='',
                    action=action,
                    data=data
                ))
            return
        else:
            data = 'id={}'.format(instance.id)
        links = ', '.join(
            '{}({})'.format(list(column.foreign_keys)[0].column.table.name, getattr(instance, name))
            for name, column in instance.__table__.columns.items()
            if column.foreign_keys and getattr(instance, name)
        )
        who = AdminAccount.admin_name() or (current_thread().name if current_thread().daemon else 'non-admin')

        def _insert(session):
            session.add(Tracking(
                model=instance.__class__.__name__,
                fk_id=instance.id,
                which=repr(instance),
                who=who,
                links=links,
                action=action,
                data=data
            ))
        if instance.session:
            _insert(instance.session)
        else:
            with Session() as session:
                _insert(session)

    @classmethod
    def track_pageview(cls, url, query):
        # Track any views of the budget pages
        if "budget" in url:
            Tracking.track(c.PAGE_VIEWED, "Budget")
        else:
            # Only log the page view if there's a valid attendee ID
            params = dict(parse_qsl(query))
            if 'id' not in params or params['id'] == 'None':
                return

            # Looking at an attendee's details
            if "registration" in url:
                with Session() as session:
                    attendee = session.query(Attendee).filter(Attendee.id == params['id']).first()
                    Tracking.track(c.PAGE_VIEWED, attendee)
            # Looking at a group's details
            elif "groups" in url:
                with Session() as session:
                    group = session.query(Group).filter(Group.id == params['id']).first()
                    Tracking.track(c.PAGE_VIEWED, group)

Tracking.UNTRACKED = [Tracking, Email]


def _make_getter(model):
    def getter(self, params=None, *, bools=(), checkgroups=(), allowed=(), restricted=False, ignore_csrf=False, **query):
        if query:
            return self.query(model).filter_by(**query).one()
        elif isinstance(params, str):
            return self.query(model).filter_by(id=params).one()
        else:
            params = params.copy()
            id = params.pop('id', 'None')
            if id == 'None':
                inst = model()
            else:
                inst = self.query(model).filter_by(id=id).one()

            if not ignore_csrf:
                assert not {k for k in params if k not in allowed} or cherrypy.request.method == 'POST', 'POST required'
            inst.apply(params, bools=bools, checkgroups=checkgroups, restricted=restricted, ignore_csrf=ignore_csrf)
            return inst
    return getter


def _presave_adjustments(session, context, instances='deprecated'):
    c.BADGE_LOCK.acquire()
    for model in chain(session.dirty, session.new):
        model.presave_adjustments()
    for model in session.deleted:
        model.predelete_adjustments()


def _release_badge_lock(session, context):
    try:
        c.BADGE_LOCK.release()
    except:
        log.error('failed releasing c.BADGE_LOCK after session flush; this should never actually happen, but we want to just keep going if it ever does')


def _release_badge_lock_on_error(*args, **kwargs):
    try:
        c.BADGE_LOCK.release()
    except:
        log.warn('failed releasing c.BADGE_LOCK on db error; these errors should not happen in the first place and we do not expect releasing the lock to fail when they do, but we still want to keep going if/when this does occur')


def _track_changes(session, context, instances='deprecated'):
    for action, instances in {c.CREATED: session.new, c.UPDATED: session.dirty, c.DELETED: session.deleted}.items():
        for instance in instances:
            if instance.__class__ not in Tracking.UNTRACKED:
                Tracking.track(action, instance)


def register_session_listeners():
    listen(Session.session_factory, 'before_flush', _presave_adjustments)
    listen(Session.session_factory, 'before_flush', _track_changes)
    listen(Session.session_factory, 'after_flush', _release_badge_lock)
    listen(Session.engine, 'dbapi_error', _release_badge_lock_on_error)
register_session_listeners()


def initialize_db():
    """
    Initialize the database on startup

    We want to do this only after all other plugins have had a chance to initialize
    and add their 'mixin' data (i.e. extra colums) into the models.

    Also, it's possible that the DB is still initializing and isn't ready to accept connections, so,
    if this fails, keep trying until we're able to connect.

    This should be the ONLY spot (except for maintenance tools) in all of core ubersystem or any plugins
    that attempts to create tables by passing modify_tables=True to Session.initialize_db()
    """
    for _model in Session.all_models():
        setattr(Session.SessionMixin, _model.__tablename__, _make_getter(_model))

    num_tries_remaining = 10
    while not stopped.is_set():
        try:
            Session.initialize_db(modify_tables=True)
        except KeyboardInterrupt:
            log.critical('DB initialize: Someone hit Ctrl+C while we were starting up')
        except:
            num_tries_remaining -= 1
            if num_tries_remaining == 0:
                log.error("DB initialize: couldn't connect to DB, we're giving up")
                raise
            log.error("DB initialize: can't connect to / initialize DB, will try again in 5 seconds", exc_info=True)
            stopped.wait(5)
        else:
            break


@on_startup
def _attendee_validity_check():
    orig_getter = Session.SessionMixin.attendee

    @wraps(orig_getter)
    def with_validity_check(self, *args, **kwargs):
        allow_invalid = kwargs.pop('allow_invalid', False)
        attendee = orig_getter(self, *args, **kwargs)
        if not allow_invalid and not attendee.is_new and attendee.badge_status == c.INVALID_STATUS:
            raise HTTPRedirect('../preregistration/invalid_badge?id={}', attendee.id)
        else:
            return attendee
    Session.SessionMixin.attendee = with_validity_check

on_startup(initialize_db, priority=1)
