from uber.common import *

def check_if_can_reg(func):
    @wraps(func)
    def with_check(*args,**kwargs):
        if state.BADGES_SOLD >= MAX_BADGE_SALES:
            return '''
                    <html><head></head><body style='text-align:center'>
                        <h2 style='color:red'>''' + EVENT_NAME + ''' has sold out.</h2>
                        Thanks to everyone who pre-registered! <br/> <br/>
                        We'll see you September 12th - 14th.
                    </body></html>
                '''
        elif state.PREREG_OPEN == "notopenyet":
            return '''
                    <html><head></head><body style='text-align:center'>
                        <h2 style='color:red'>''' + EVENT_NAME + ''' pre-registration is not yet open.</h2>
                        Please check back on May 15th.
                    </body></html>
                '''
        elif state.PREREG_OPEN == "closed":
            return '''
                    <html><head></head><body style='text-align:center'>
                        <h2 style='color:red'>''' + EVENT_NAME + ''' pre-registration has closed.</h2>
                        We'll see everyone September 12th - 14th. <br/> <br/>
                        Full weekend passes will be available at the door for $60. There will not be any single-day passes available - apologies for any inconvenience this causes.
                    </body></html>
                '''
        else:
            return func(*args,**kwargs)
    return with_check

def site_mappable(func):
    func.site_mappable = True
    return func


def cached_property(func):
    pname = '_' + func.__name__
    @property
    @wraps(func)
    def caching(self, *args, **kwargs):
        if not hasattr(self, pname):
            setattr(self, pname, func(self, *args, **kwargs))
        return getattr(self, pname)
    return caching


def show_queries(func):
    @wraps(func)
    def queries(self, *args, **kwargs):
        connection.queries[:] = []
        stripped = [arg for arg in args if arg != 'querylog']
        try:
            return func(self, *stripped, **kwargs)
        finally:
            if 'querylog' in args:
                cherrypy.response.headers['Content-type'] = 'text/plain'
                return pformat(connection.queries)
    return queries


def csrf_protected(func):
    @wraps(func)
    def protected(*args, csrf_token, **kwargs):
        check_csrf(csrf_token)
        return func(*args, **kwargs)
    return protected


# requires: POST and a valid CSRF token
def ajax(func):
    @wraps(func)
    def returns_json(*args, **kwargs):
        cherrypy.response.headers['Content-Type'] = 'application/json'
        assert cherrypy.request.method == 'POST', 'POST required'
        check_csrf(kwargs.pop('csrf_token', None))
        return json.dumps(func(*args, **kwargs)).encode('utf-8')
    return returns_json

# used for things that should be publicly called, i.e. APIs and such.
# supports GET or POST
def ajax_public_callable(func):
    @wraps(func)
    def returns_json(*args, **kwargs):
        cherrypy.response.headers['Content-Type'] = 'application/json'
        return json.dumps(func(*args, **kwargs)).encode('utf-8')
    return returns_json


def csv_file(func):
    @wraps(func)
    def csvout(self):
        cherrypy.response.headers['Content-Type'] = 'application/csv'
        cherrypy.response.headers['Content-Disposition'] = 'attachment; filename=' + func.__name__ + '.csv'
        writer = StringIO()
        func(self, csv.writer(writer))
        return writer.getvalue().encode('utf-8')
    return csvout


def credit_card(func):
    @wraps(func)
    def charge(self, payment_id, stripeToken, **ignored):
        if ignored:
            log.error('received unexpected stripe parameters: {}', ignored)
        try:
            return func(self, payment_id=payment_id, stripeToken=stripeToken)
        except HTTPRedirect:
            raise
        except:
            send_email(ADMIN_EMAIL, [ADMIN_EMAIL, 'dom@magfest.org'], 'MAGFest Stripe error',
                       'Got an error while calling charge(self, payment_id={!r}, stripeToken={!r}, ignored={}):\n{}'
                       .format(payment_id, stripeToken, ignored, traceback.format_exc()))
            return traceback.format_exc()
    return charge


def renderable_data(data = None):
    data = data or {}
    data.update({m.__name__: m for m in all_models()})
    data.update({k: v for k,v in constants.__dict__.items() if re.match('^[_A-Z0-9]*$', k)})
    data.update({k: getattr(state, k) for k in dir(state) if re.match('^[_A-Z0-9]*$', k)})
    data.update({
        'now':   datetime.now(),
        'PAGE':  cherrypy.request.path_info.split('/')[-1]
    })
    try:
        data['CSRF_TOKEN'] = cherrypy.session['csrf_token']
    except:
        pass
    
    access = AdminAccount.access_set()
    for acctype in ['ACCOUNTS','PEOPLE','STUFF','MONEY','CHALLENGES','CHECKINS']:
        data['HAS_' + acctype + '_ACCESS'] = getattr(constants, acctype) in access
    
    return data

def render(template, data = None):
    data = renderable_data(data)
    rendered = loader.get_template(template).render( Context(data) )
    if not AT_THE_CON and AdminAccount.is_nick() and 'emails' not in template and 'history' not in template and 'form' not in rendered:
        rendered = rendered.replace('festival', 'convention').replace('Fest', 'Con')
    return rendered.encode('utf-8')

# TODO: sanitize for XSS attacks; currently someone can only attack themselves, but still...
def ng_render(fname, **kwargs):
    class AngularTemplate(string.Template):
        delimiter = '%__'
    
    with open(os.path.join(MODULE_ROOT, 'templates', fname)) as f:
        data = {k: (str(v).lower() if v in [True, False] else v) for k, v in renderable_data(kwargs).items()}
        return AngularTemplate(f.read()).substitute(**data)


def _get_module_name(class_or_func):
    return class_or_func.__module__.split('.')[-1]

def _get_template_filename(func):
    return os.path.join(_get_module_name(func), func.__name__ + '.html')

def ng_renderable(func):
    @wraps(func)
    def with_rendering(*args, **kwargs):
        result = func(*args, **kwargs)
        return result if isinstance(result, str) else ng_render(_get_template_filename(func), **result)
    
    spec = inspect.getfullargspec(func)
    if spec.args == ['self'] and not spec.varargs and not spec.varkw:
        return site_mappable(with_rendering)
    else:
        return with_rendering

def renderable(func):
    @wraps(func)
    def with_rendering(*args, **kwargs):
        result = func(*args, **kwargs)
        if isinstance(result, dict):
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
            if func.restricted == (SIGNUPS,):
                if not cherrypy.session.get('staffer_id'):
                    raise HTTPRedirect('../signups/login?message=You+are+not+logged+in')
            
            elif cherrypy.session.get('account_id') is None:
                raise HTTPRedirect('../accounts/login?message=You+are+not+logged+in')
            
            else:
                if not set(func.restricted).intersection(AdminAccount.access_set()):
                    if len(func.restricted) == 1:
                        return 'You need {} access for this page'.format(dict(ACCESS_OPTS)[func.restricted[0]])
                    else:
                        return ('You need at least one of the following access levels to view this page: '
                            + ', '.join(dict(ACCESS_OPTS)[r] for r in func.restricted))
        
        return func(*args, **kwargs)
    return with_restrictions

class all_renderable:
    def __init__(self, *needs_access, angular=False):
        self.angular = angular
        self.needs_access = needs_access
    
    def __call__(self, klass):
        if self.angular:
            def ng(self, template):
                return ng_render(os.path.join(_get_module_name(klass), 'angular', template))
            klass.ng = ng
        
        for name,func in klass.__dict__.items():
            if hasattr(func, '__call__'):
                func.restricted = getattr(func, 'restricted', self.needs_access)
                new_func = show_queries(restricted(renderable(func)))
                new_func.exposed = True
                new_func._orig = func
                setattr(klass, name, new_func)
        return klass


register = template.Library()
def tag(klass):
    @register.tag(klass.__name__)
    def tagged(parser, token):
        return klass(*token.split_contents()[1:])
    return klass
