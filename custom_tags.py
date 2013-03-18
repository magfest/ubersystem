from __future__ import division
from common import *

@register.filter
def datetime(dt, fmt):
    return " ".join(dt.strftime(fmt).split())

@register.filter
def timestamp(dt):
    import time
    return str(int(time.mktime(dt.timetuple())))

@register.filter
def jsonize(x):
    return SafeString( json.dumps(x) )

@register.filter
def remove_newlines(string):
    return string.replace("\n", " ")

@register.filter
def time_day(dt):
    return SafeString("<nobr>{} {}</nobr>".format(dt.strftime("%I:%M%p").lstrip("0").lower(), dt.strftime("%a")))

@register.filter
def idize(s):
    return re.sub("\W+", "_", str(s)).strip("_")

@register.filter
def maybe_red(amount, comp):
    if amount >= comp:
        return SafeString('<span style="color:red ; font-weight:bold">{}</span>'.format(amount))
    else:
        return amount

@register.filter
def maybe_last_year(day):
    return "last year" if day <= STAFFERS_IMPORTED else day

@register.filter
def join_and(xs):
    if len(xs) in [0, 1, 2]:
        return " and ".join(xs)
    else:
        xs = xs[:-1] + ["and " + xs[-1]]
        return ", ".join(xs)

@tag
class maybe_anchor(template.Node):
    def __init__(self, name):
        self.name = Variable(name)
    
    def render(self, context):
        name = self.name.resolve(context)
        letter = name.upper()[0]
        if letter != context.get("letter"):
            context["letter"] = letter
            return '<a name="{}"></a>'.format(letter)
        else:
            return ""

counters = local()
@tag
class zebra(template.Node):
    def __init__(self, name, param=""):
        self.name, self.param = name, param
    
    def render(self, context):
        counter = getattr(counters, self.name, 0)
        if self.param == "start":
            counter = 0
        elif self.param != "noinc":
            counter = (counter + 1) % 2
        setattr(counters, self.name, counter)
        return ["#ffffff","#eeeeee"][counter]

@tag
class options(template.Node):
    def __init__(self, options, default='""'):
        self.options = Variable(options)
        self.default = default[1:-1] if default[0]=='"' else Variable(default)
    
    def render(self, context):
        options = self.options.resolve(context)
        default = self.default
        if isinstance(default, Variable):
            try:
                default = default.resolve(context)
            except:
                default = ""
        
        results = []
        for opt in options:
            if len(listify(opt)) == 1:
                opt = [opt, opt]
            val, desc = opt
            selected = "selected" if str(val)==str(default) else ""
            val  = str(val).replace('"',  "&quot;").replace("\n", "")
            desc = str(desc).replace('"', "&quot;").replace("\n", "")
            results.append("""<option value="%s" %s>%s</option>""" % (val, selected, desc))
        return "\n".join(results)

@tag
class checkgroup(template.Node):
    def __init__(self, name, options, defaults=None, newlines=None):
        self.name     = name[1:-1]
        self.options  = Variable(options)
        self.defaults = Variable(defaults) if defaults else []
        self.newlines = Variable(newlines) if newlines else []
    
    def render(self, context):
        options  = self.options.resolve(context)
        defaults = self.defaults
        if isinstance(defaults, Variable):
            defaults = defaults.resolve(context).split(",")
        newline = "<br/>" if self.newlines else ""
        
        results = []
        for num,desc in options:
            checked = "checked" if str(num) in defaults else ""
            results.append("""<nobr><input type="checkbox" name="%s" value="%s" %s /> %s</nobr>""" % (self.name, num, checked, desc))
        return ("&nbsp;&nbsp;%s\n" % newline).join(results)

@tag
class int_options(template.Node):
    def __init__(self, minval, maxval, default="1"):
        self.minval  = int(minval)
        self.maxval  = int(maxval) if maxval.isdigit() else Variable(maxval)
        self.default = int(default) if default.isdigit() else Variable(default)
    
    def render(self, context):
        maxval  = self.maxval  if isinstance(self.maxval,  int) else self.maxval.resolve(context)
        try:
            default = self.default if isinstance(self.default, int) else int(self.default.resolve(context))
        except:
            default = 1
        
        results = []
        for i in range(self.minval, maxval+1):
            selected = "selected" if i==default else ""
            results.append('<option value="{val}" {selected}>{val}</option>'.format(val=i, selected=selected))
        return "\n".join(results)

@tag
class radio(template.Node):
    def __init__(self, name, value, default):
        self.name    = name[1:-1]
        self.value   = Variable(value)
        self.default = Variable(default)
    
    def render(self, context):
        value   = self.value.resolve(context)
        default = self.default.resolve(context)
        checked = "checked" if str(value)==str(default) else ""
        
        return """<input type="radio" name="%s" value="%s" %s />""" % (self.name, value, checked)

@tag
class hour_day(template.Node):
    def __init__(self, dt):
        self.dt = Variable(dt)
    
    def render(self, context):
        return hour_day_format( self.dt.resolve(context) )

@tag
class timespan(template.Node):
    def __init__(self, model):
        self.model = Variable(model)
    
    def render(self, context):
        model = self.model.resolve(context)
        
        endtime  = model.start_time + timedelta(hours=model.duration)
        startstr = model.start_time.strftime("%I").lstrip("0")
        endstr   = endtime.strftime("%I").lstrip("0") + endtime.strftime("%p").lower()
        
        if model.start_time.day==endtime.day:
            endstr += endtime.strftime(" %A")
            if model.start_time.hour<12 and endtime.hour>=12:
                return startstr + "am - " + endstr
            else:
                return startstr + "-" + endstr
        else:
            return startstr + model.start_time.strftime("pm %a - ") + endstr + endtime.strftime(" %a")

@tag
class popup_link(template.Node):
    def __init__(self, href, text='"<sup>?</sup>"'):
        self.href = href.strip('"')
        self.text = text.strip('"')
    
    def render(self, context):
        return """
            <a onClick="window.open('%s', 'info', 'toolbar=no,height=500,width=375,scrollbars=yes').focus(); return false;"
               href="%s">%s</a>""" % (self.href, self.href, self.text)

@tag
class must_contact(template.Node):
    def __init__(self, staffer):
        self.staffer = Variable(staffer)
    
    def render(self, context):
        staffer = self.staffer.resolve(context)
        locations = [s.job.location for s in staffer.shifts]
        dept_names = dict(JOB_LOC_OPTS)
        return "<br/>".join({"{} ({})".format(DEPT_CHAIRS[dept], dept_names[dept]) for dept in locations})

@tag
class add_max_lengths(template.Node):
    def __init__(self, model_name):
        self.model_name = model_name
    
    def render(self, context):
        import models
        klass = getattr(models, self.model_name)
        
        lines = []
        for field in klass._meta.fields:
            if isinstance(field, CharField):
                lines.append("""$("input[type=text][name={}]").attr("maxlength", "{}");""" 
                             .format(field.name, field.max_length))
        
        return """<script type="text/javascript">{}</script>""".format("\n".join(lines))

@tag
class pages(template.Node):
    def __init__(self, page, count):
        self.page, self.count = Variable(page), Variable(count)
    
    def render(self, context):
        page = int(self.page.resolve(context))
        count = self.count.resolve(context)
        pages = []
        for pagenum in range(1, int(math.ceil(count / 100)) + 1):
            if pagenum == page:
                pages.append(pagenum)
            else:
                path = cherrypy.request.request_line.split()[1].split("/")[-1]  # TODO: don't parse the entire request line
                page_qs = "page={}".format(pagenum)
                if "page=" in path:
                    path = re.sub(r"page=\d+", page_qs, path)
                else:
                    path += ("&" if "?" in path else "?") + page_qs
                pages.append('<a href="{}">{}</a>'.format(path, pagenum))
        return "Page: " + " ".join(map(str, pages))

def extract_fields(what):
    if isinstance(what, Attendee):
        return "a{}".format(what.id), what.full_name, what.total_cost
    elif isinstance(what, Group):
        return "g{}".format(what.id), what.name, what.amount_unpaid
    else:
        return None, None, None

@register.filter
def paypal_url(what):
    ids, names, amount = extract_fields(what)
    url = ("{action}?cmd=_xclick"
           "&business=magfest.prereg@gmail.com"
           "&amount={amount}"
           "&item_name={names}"
           "&item_number={ids}"
           "&rm=2"
           "&return={return_url}")
    return SafeString(url.format(ids=ids, names=quote(names), amount=amount, action=PAYPAL_ACTION, return_url=quote(PAYPAL_RETURN_URL)))

@tag
class paypal_button(template.Node):
    def __init__(self, what, ids = None, amount = None):
        self.what   = Variable(what)
        self.ids    = ids and Variable(ids)
        self.amount = amount and Variable(amount)

    def render(self, context):
        what = self.what.resolve(context)
        ids, names, amount = extract_fields(what)
        if not ids:
            ids     = self.ids.resolve(context)
            names   = what
        if self.amount is not None:
            amount = self.amount.resolve(context)
        
        return """
            <form target="_ppprereg" action="{action}" method="post">
                <input type="hidden" name="cmd"         value="_xclick" />
                <input type="hidden" name="business"    value="magfest.prereg@gmail.com" />
                <input type="hidden" name="item_name"   value="MAGFest Prereg: {names}" />
                <input type="hidden" name="item_number" value="{ids}" />
                <input type="hidden" name="amount"      value="{amount}" />
                <input type="hidden" name="return"      value="{return_url}" />
                <input type="hidden" name="rm"          value="2" />
                <input type="image"  name="submit" src="../static/paypal.gif" />
            </form>
        """.format(ids=ids, names=names, amount=amount, action=PAYPAL_ACTION, return_url=PAYPAL_RETURN_URL)

@tag
class nav_menu(template.Node):
    def __init__(self, inst, *items):
        self.inst = Variable(inst)
        self.menu_items = []
        for i in range(0, len(items), 3):
            href, label, display = items[i : i + 3]
            self.menu_items.append([href[1:-1], label[1:-1], display])
    
    def is_visible(self, display, context):
        bools = {"True": True, "False": False}
        return bools[display] if display in bools else Variable(display).resolve(context)
    
    def render(self, context):
        inst = self.inst.resolve(context)
        if not inst.id:
            return ""
        
        pages = [(href.format(**inst.__dict__), label)
                 for href, label, display in self.menu_items
                 if self.is_visible(display, context)]
        
        width = 100 // len(pages)
        items = ['<table class="menu"><tr>']
        for href, label in pages:
            if cherrypy.request.path_info.endswith(href.split("?")[0]):
                link = label
            else:
                link = '<a href="{}">{}</a>'.format(href, label)
            items.append('<td width="{}%">{}</td>'.format(width, link))
        return "\n".join(items + ["</tr></table>"])

@tag
class checkbox(template.Node):
    def __init__(self, name, inst, value = None, checked = None):
        self.name, self.inst, self.value, self.checked = name, Variable(inst), value, checked
    
    def render(self, context):
        inst = self.inst.resolve(context)
        value = Variable(self.value).resolve(context) if self.value else "1"
        cond = Variable(self.checked).resolve(context) if self.checked else getattr(inst, self.name)
        checked = "checked" if cond else ""
        return '<input type="checkbox" name="{}" value="{}" {} />'.format(self.name, value, checked)

@tag
class checked_if(template.Node):
    def __init__(self, *args):
        self.negated = len(args) > 1
        self.cond = Variable(args[-1])
    
    def render(self, context):
        try:
            cond = self.cond.resolve(context)
        except:
            cond = False
        checked = self.negated and not cond or not self.negated and cond
        image = "checked" if checked else "unchecked"
        return '<img src="../static/checkbox_{}.png" style="vertical-align:top ; margin-right:5px" height="20" width="20" />'.format(image)


@tag
class csrf_token(template.Node):
    def render(self, context):
        return '<input type="hidden" name="csrf_token" value="{}" />'.format(cherrypy.session["csrf_token"])


@register.tag("bold_if")
def do_bold_if(parser, token):
    [cond] = token.split_contents()[1:]
    nodelist = parser.parse(('end_bold_if',))
    parser.delete_first_token()
    return BoldIfNode(cond, nodelist)

class BoldIfNode(template.Node):
    def __init__(self, cond, nodelist):
        self.cond = Variable(cond)
        self.nodelist = nodelist
    
    def render(self, context):
        cond = self.cond.resolve(context)
        output = self.nodelist.render(context)
        if cond:
            return "<b>" + output + "</b>"
        else:
            return output
