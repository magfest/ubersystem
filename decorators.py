from common import *

def cached_property(func):
    pname = "_" + func.__name__
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
        stripped = [arg for arg in args if arg != "querylog"]
        try:
            return func(self, *stripped, **kwargs)
        finally:
            if "querylog" in args:
                cherrypy.response.headers["Content-type"] = "text/plain"
                return pformat(connection.queries)
    return queries


def csrf_protected(func):
    @wraps(func)
    def protected(*args, csrf_token, **kwargs):
        check_csrf(csrf_token)
        return func(*args, **kwargs)
    return protected


def ajax(func):
    @wraps(func)
    def returns_json(*args, **kwargs):
        cherrypy.response.headers["Content-Type"] = "application/json"
        assert cherrypy.request.method == "POST", "POST required"
        check_csrf(kwargs.pop("csrf_token", None))
        return json.dumps(func(*args, **kwargs)).encode("utf-8")
    return returns_json


def csv_file(func):
    @wraps(func)
    def csvout(self):
        cherrypy.response.headers["Content-Type"] = "application/csv"
        cherrypy.response.headers["Content-Disposition"] = "attachment; filename=" + func.__name__ + ".csv"
        writer = StringIO()
        func(self, csv.writer(writer))
        return writer.getvalue()
    return csvout


def credit_card(func):
    @wraps(func)
    def charge(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except HTTPRedirect:
            raise
        except:
            # TODO: email eli a stacktrace and return a template
            return traceback.format_exc()
    return charge


def render(template, data = None):
    import constants
    from models import Account, all_models
    data = data or {}
    data.update({m.__name__: m for m in all_models()})
    data.update({k: v for k,v in constants.__dict__.items() if re.match("^[_A-Z0-9]*$", k)})
    data.update({k: getattr(state, k) for k in dir(state) if re.match("^[_A-Z0-9]*$", k)})
    data.update({
        "now":   datetime.now(),
        "PAGE":  cherrypy.request.path_info.split("/")[-1]
    })
    try:
        data["CSRF_TOKEN"] = cherrypy.session["csrf_token"]
    except:
        pass
    
    access = Account.access_set()
    for acctype in ["ACCOUNTS","PEOPLE","STUFF","MONEY","CHALLENGES","CHECKINS"]:
        data["HAS_" + acctype + "_ACCESS"] = getattr(constants, acctype) in access
    
    rendered = loader.get_template(template).render( Context(data) )
    if not state.AT_THE_CON and Account.admin_name() == "Nick Marinelli":
        rendered = rendered.replace("Fest", "Con")
    return rendered


def renderable(func):
    @wraps(func)
    def with_rendering(*args, **kwargs):
        res = func(*args, **kwargs)
        if isinstance(res, dict):
            mod_name = func.__module__.split(".")[1]
            template = "{}/{}.html".format(mod_name, func.__name__)
            return render(template, res)
        else:
            return res
    return with_rendering

def unrestricted(func):
    func.restricted = False
    return func

def restricted(func):
    @wraps(func)
    def with_restrictions(*args, **kwargs):
        if func.restricted:
            if func.restricted == (SIGNUPS,):
                if not cherrypy.session.get("staffer_id"):
                    raise HTTPRedirect("../signups/login?message=You+are+not+logged+in")
            
            elif cherrypy.session.get("account_id") is None:
                raise HTTPRedirect("../accounts/login?message=You+are+not+logged+in")
            
            else:
                from models import Account
                if not set(func.restricted).intersection( Account.access_set() ):
                    if len(func.restricted) == 1:
                        return "You need {} access for this page".format(dict(ACCESS_OPTS)[func.restricted[0]])
                    else:
                        return ("You need at least one of the following access levels to view this page: "
                            + ", ".join(dict(ACCESS_OPTS)[r] for r in func.restricted))
        
        return func(*args, **kwargs)
    return with_restrictions

class all_renderable:
    def __init__(self, *needs_access):
        self.needs_access = needs_access
    
    def __call__(self, klass):
        for name,func in klass.__dict__.items():
            if hasattr(func, "__call__"):
                func.restricted = getattr(func, "restricted", self.needs_access)
                new_func = show_queries(restricted(renderable(func)))
                new_func.exposed = True
                setattr(klass, name, new_func)
        return klass


register = template.Library()
def tag(klass):
    @register.tag(klass.__name__)
    def tagged(parser, token):
        return klass(*token.split_contents()[1:])
    return klass
