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
        args = [arg for arg in args if arg != "querylog"]
        try:
            return func(self, *args, **kwargs)
        finally:
            if "querylog" in args:
                cherrypy.response.headers["Content-type"] = "text/plain"
                return pformat(connection.queries)
    return queries



def ajax(func):
    @wraps(func)
    def returns_json(self, *args, **kwargs):
        cherrypy.response.headers["Content-Type"] = "application/json"
        return json.dumps(func(self, *args, **kwargs))
    return returns_json



constant_fields = {attrname: attr for attrname,attr in constants.__dict__.items() if re.match("^[_A-Z0-9]*$",attrname)}
def render(template, data = None):
    data = {} if data is None else data
    data.update(constant_fields)
    data.update({
        "state": state,
        "now":   datetime.now(),
        "PAGE":  cherrypy.request.path_info.split("/")[-1]
    })
    
    from models import Account
    access = Account.access_set()
    for acctype in ["ACCOUNTS","PEOPLE","STUFF","MONEY","CHALLENGES","CHECKINS"]:
        if getattr(constants, acctype) in access:
            data["HAS_" + acctype + "_ACCESS"] = True
    
    return loader.get_template(template).render( Context(data) )



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

