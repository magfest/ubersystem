from uber.common import *


def log_pageview(func):
    @wraps(func)
    def with_check(*args, **kwargs):
        with sa.Session() as session:
            try:
                attendee = session.admin_account(cherrypy.session['account_id'])
            except:
                pass  # we don't care about unrestricted pages for this version
            else:
                sa.Tracking.track_pageview(cherrypy.request.path_info, cherrypy.request.query_string)
        return func(*args, **kwargs)
    return with_check


def check_if_can_reg(func):
    @wraps(func)
    def with_check(*args, **kwargs):
        if c.BADGES_SOLD >= c.MAX_BADGE_SALES:
            return render('static_views/prereg_soldout.html')
        elif c.BEFORE_PREREG_OPEN:
            return render('static_views/prereg_not_yet_open.html')
        elif c.AFTER_PREREG_TAKEDOWN and not c.AT_THE_CON:
            return render('static_views/prereg_closed.html')
        return func(*args, **kwargs)
    return with_check


def get_innermost(func):
    return get_innermost(func.__wrapped__) if hasattr(func, '__wrapped__') else func


def site_mappable(func):
    func.site_mappable = True
    return func


def suffix_property(func):
    func._is_suffix_property = True
    return func


def _suffix_property_check(inst, name):
    if not name.startswith('_'):
        suffix = '_' + name.rsplit('_', 1)[-1]
        prop_func = getattr(inst, suffix, None)
        if getattr(prop_func, '_is_suffix_property', False):
            field_name = name[:-len(suffix)]
            field_val = getattr(inst, field_name)
            return prop_func(field_name, field_val)

suffix_property.check = _suffix_property_check


def csrf_protected(func):
    @wraps(func)
    def protected(*args, csrf_token, **kwargs):
        check_csrf(csrf_token)
        return func(*args, **kwargs)
    return protected


def ajax(func):
    """decorator for Ajax POST requests which require a CSRF token and return JSON"""
    @wraps(func)
    def returns_json(*args, **kwargs):
        cherrypy.response.headers['Content-Type'] = 'application/json'
        assert cherrypy.request.method == 'POST', 'POST required, got {}'.format(cherrypy.request.method)
        check_csrf(kwargs.pop('csrf_token', None))
        return json.dumps(func(*args, **kwargs), cls=serializer).encode('utf-8')
    return returns_json


def ajax_gettable(func):
    """
    Decorator for page handlers which return JSON.  Unlike the above @ajax decorator,
    this allows either GET or POST and does not check for a CSRF token, so this can
    be used for pages which supply data to external APIs as well as pages used for
    periodically polling the server for new data by our own Javascript code.
    """
    @wraps(func)
    def returns_json(*args, **kwargs):
        cherrypy.response.headers['Content-Type'] = 'application/json'
        return json.dumps(func(*args, **kwargs), cls=serializer).encode('utf-8')
    return returns_json


def multifile_zipfile(func):
    @wraps(func)
    def zipfile_out(self, session):
        zipfile_writer = BytesIO()
        with zipfile.ZipFile(zipfile_writer, mode='w') as zip_file:
            func(self, zip_file, session)

        # must do this after creating the zip file as other decorators may have changed this
        # for example, if a .zip file is created from several .csv files, they may each set content-type.
        cherrypy.response.headers['Content-Type'] = 'application/zip'
        cherrypy.response.headers['Content-Disposition'] = 'attachment; filename=' + func.__name__ + '.zip'

        return zipfile_writer.getvalue()
    return zipfile_out


def csv_file(func):
    @wraps(func)
    def csvout(self, session, **kwargs):
        cherrypy.response.headers['Content-Type'] = 'application/csv'
        cherrypy.response.headers['Content-Disposition'] = 'attachment; filename=' + func.__name__ + '.csv'
        writer = StringIO()
        func(self, csv.writer(writer), session, **kwargs)
        return writer.getvalue().encode('utf-8')
    return csvout


def check_shutdown(func):
    @wraps(func)
    def with_check(self, *args, **kwargs):
        if c.UBER_SHUT_DOWN or c.AT_THE_CON:
            raise HTTPRedirect('index?message={}', 'The page you requested is only available pre-event.')
        else:
            return func(self, *args, **kwargs)
    return with_check


def credit_card(func):
    @wraps(func)
    def charge(self, session, payment_id, stripeToken, stripeEmail='ignored', **ignored):
        if ignored:
            log.error('received unexpected stripe parameters: {}', ignored)
        try:
            return func(self, session=session, payment_id=payment_id, stripeToken=stripeToken)
        except HTTPRedirect:
            raise
        except:
            send_email(c.ADMIN_EMAIL, [c.ADMIN_EMAIL, 'dom@magfest.org'], 'MAGFest Stripe error',
                       'Got an error while calling charge(self, payment_id={!r}, stripeToken={!r}, ignored={}):\n{}'
                       .format(payment_id, stripeToken, ignored, traceback.format_exc()))
            return traceback.format_exc()
    return charge


def cached(func):
    func.cached = True
    return func


def cached_page(func):
    from sideboard.lib import config as sideboard_config
    innermost = get_innermost(func)
    func.lock = RLock()

    @wraps(func)
    def with_caching(*args, **kwargs):
        if hasattr(innermost, 'cached'):
            fpath = os.path.join(sideboard_config['root'], 'data', func.__module__ + '.' + func.__name__)
            with func.lock:
                if not os.path.exists(fpath) or datetime.now().timestamp() - os.stat(fpath).st_mtime > 60 * 15:
                    contents = func(*args, **kwargs)
                    with open(fpath, 'wb') as f:
                        # Try to write assuming content is a byte first, then try it as a string
                        try:
                            f.write(contents)
                        except:
                            f.write(bytes(contents, 'UTF-8'))
                with open(fpath, 'rb') as f:
                    return f.read()
        else:
            return func(*args, **kwargs)
    return with_caching


def timed(func):
    @wraps(func)
    def with_timing(*args, **kwargs):
        before = datetime.now()
        try:
            return func(*args, **kwargs)
        finally:
            log.debug('{}.{} loaded in {} seconds'.format(func.__module__, func.__name__, (datetime.now() - before).total_seconds()))
    return with_timing


def sessionized(func):
    @wraps(func)
    def with_session(*args, **kwargs):
        innermost = get_innermost(func)
        if 'session' not in inspect.getfullargspec(innermost).args:
            return func(*args, **kwargs)
        else:
            with sa.Session() as session:
                try:
                    retval = func(*args, session=session, **kwargs)
                    session.expunge_all()
                    return retval
                except HTTPRedirect:
                    session.commit()
                    raise
    return with_session


def renderable_data(data=None):
    data = data or {}
    data['c'] = c
    data.update({m.__name__: m for m in sa.Session.all_models()})
    return data


# TODO: replace with a nicer way to initialize this
# for now we initialize the first time it's called.
# TODO: need to not use django settings (they'll be ripped out later) for TEMPLATE_DIRS
# TODO: setup filters in a separate function, probably. probably same way as custom_tags.py
# TODO: port over everything in custom_tags.py to hook in here
class JinjaEnv:
    _env = None
    _exportable_functions = {}
    _filter_functions = {}

    @staticmethod
    def env():
        if JinjaEnv._env is None:
            JinjaEnv._env = JinjaEnv._init_env()
        return JinjaEnv._env

    @staticmethod
    def _init_env():
        env = jinja2.Environment(
                # autoescape=_guess_autoescape,
                loader=jinja2.FileSystemLoader(django.conf.settings.TEMPLATE_DIRS) # TODO: kill django reference
            )

        for name, func in JinjaEnv._exportable_functions.items():
            env.globals[name] = func

        for name, func in JinjaEnv._filter_functions.items():
            env.filters[name] = func

        return env

    @staticmethod
    def jinja_export(name=None):
        def wrap(func):
            JinjaEnv._exportable_functions[name if name else func.__name__] = func
            return func
        return wrap

    @staticmethod
    def jinja_filter(name=None):
        def wrap(func):
            JinjaEnv._filter_functions[name if name else func.__name__] = func
            return func
        return wrap


# render using the first template that actually exists in template_name_list
# uses JINJA2 - new style
def render(template_name_list, data=None):
    data = renderable_data(data)
    env = JinjaEnv.env()
    template = env.get_template(template_name_list)
    rendered = template.render(data)
    rendered = screw_you_nick(rendered, template)  # lolz.
    return rendered


# this is a Magfest inside joke.
# Nick gets mad when people call Magfest a "convention".  He always says "It's not a convention, it's a festival"
# So........ if Nick is logged in.... let's annoy him a bit :)
def screw_you_nick(rendered, template):
    if not c.AT_THE_CON and sa.AdminAccount.is_nick() and 'emails' not in template and 'history' not in template and 'form' not in rendered:
        return rendered.replace('festival', 'convention').replace('Fest', 'Con')  # lolz.
    else:
        return rendered


def _get_module_name(class_or_func):
    return class_or_func.__module__.split('.')[-1]


def _get_template_filename(func):
    return os.path.join(_get_module_name(func), func.__name__ + '.html')


def renderable(func):
    @wraps(func)
    def with_rendering(*args, **kwargs):
        result = func(*args, **kwargs)
        if c.UBER_SHUT_DOWN and not cherrypy.request.path_info.startswith('/schedule'):
            return render('closed.html')
        elif isinstance(result, dict):
            return render(_get_template_filename(func), result)
        else:
            return result
    return with_rendering


def renderable(func):
    @wraps(func)
    def with_rendering(*args, **kwargs):
        result = func(*args, **kwargs)
        if c.UBER_SHUT_DOWN and not cherrypy.request.path_info.startswith('/schedule'):
            return render('closed.html')
        elif isinstance(result, dict):
            return render(_get_template_filename(func), result)
        else:
            return result
    return with_rendering


def unrestricted(func):
    func.restricted = False
    return func


def restricted(func):
    @wraps(func)
    def with_restrictions(*args, **kwargs):
        if func.restricted:
            if func.restricted == (c.SIGNUPS,):
                if not cherrypy.session.get('staffer_id'):
                    raise HTTPRedirect('../signups/login?message=You+are+not+logged+in')

            elif cherrypy.session.get('account_id') is None:
                raise HTTPRedirect('../accounts/login?message=You+are+not+logged+in')

            else:
                access = sa.AdminAccount.access_set()
                if not c.AT_THE_CON:
                    access.discard(c.REG_AT_CON)

                if not set(func.restricted).intersection(access):
                    if len(func.restricted) == 1:
                        return 'You need {} access for this page'.format(dict(c.ACCESS_OPTS)[func.restricted[0]])
                    else:
                        return ('You need at least one of the following access levels to view this page: '
                            + ', '.join(dict(c.ACCESS_OPTS)[r] for r in func.restricted))

        return func(*args, **kwargs)
    return with_restrictions


class all_renderable:
    def __init__(self, *needs_access):
        self.needs_access = needs_access

    def __call__(self, klass):
        for name, func in klass.__dict__.items():
            if hasattr(func, '__call__'):
                func.restricted = getattr(func, 'restricted', self.needs_access)
                render_func = None
                render_func = renderable(func)

                new_func = timed(cached_page(sessionized(restricted(render_func))))
                new_func.exposed = True
                setattr(klass, name, new_func)
        return klass


register = template.Library()


def tag(klass):
    @register.tag(klass.__name__)
    def tagged(parser, token):
        return klass(*token.split_contents()[1:])
    return klass


class Validation:
    def __init__(self):
        self.validations = defaultdict(OrderedDict)

    def __getattr__(self, model_name):
        def wrapper(func):
            self.validations[model_name][func.__name__] = func
            return func
        return wrapper

validation, prereg_validation = Validation(), Validation()


adjustment_counter = count().__next__


def presave_adjustment(func):
    """
    Decorate methods on a model class with this decorator to ensure that the
    method is called immediately before the model is saved so that you can
    make any adjustments, e.g. setting a ribbon based on other information.
    """
    func.presave_adjustment = adjustment_counter()
    return func


def predelete_adjustment(func):
    """
    Decorate methods on a model class with this decorator to ensure that the
    method is called immediately before the model is deleted, e.g. to shift
    badges around the now-open slot.
    """
    func.predelete_adjustment = adjustment_counter()
    return func


class cost_property(property):
    """
    Different events have extra things they charge money for to attendees and
    groups.  Those events can use the @Session.model_mixin decorator and then
    define a @cost_property which returns the amount added.  For example, we
    have code in the MAGStock repo which looks vaguely like this:

        @Session.model_mixin
        class Attendee:
            purchased_food = Column(Boolean, default=False)

            @cost_property
            def food_price(self):
                return c.FOOD_PRICE if self.purchased_food else 0
    """


class class_property(object):
    """Read-only property for classes rather than instances."""
    def __init__(self, func):
        self.func = func

    def __get__(self, obj, owner):
        return self.func(owner)
