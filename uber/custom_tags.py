from uber.common import *

@register.filter
def datetime(dt, fmt='11:59pm EST on %A, %b %e'):
    return ' '.join(dt.astimezone(EVENT_TIMEZONE).strftime(fmt).split())

@register.filter
def timestamp(dt):
    from time import mktime
    return str(int(mktime(dt.timetuple())))

@register.filter
def jsonize(x):
    return SafeString(json.dumps(x, cls=serializer))

@register.filter
def subtract(x, y):
    return x - y

@register.filter
def remove_newlines(string):
    return string.replace('\n', ' ')

@register.filter
def form_link(attendee):
    return SafeString('<a href="../registration/form?id={}">{}</a>'.format(attendee.id, attendee.full_name))

@register.filter
def dept_checklist_path(conf, attendee=None):
    return SafeString(conf.path(attendee))

def _getter(x, attrName):
    if '.' in attrName:
        first, rest = attrName.split('.', 1)
        return _getter(getattr(x, first), rest)
    else:
        return getattr(x, attrName)

@register.filter
def sortBy(xs, attrName):
    return sorted(xs, key=lambda x: _getter(x, attrName))

@register.filter
def time_day(dt):
    return SafeString('<nobr>{} {}</nobr>'.format(dt.astimezone(EVENT_TIMEZONE).strftime('%I:%M%p').lstrip('0').lower(),
                                                  dt.astimezone(EVENT_TIMEZONE).strftime('%a')))

@register.filter
def full_datetime(dt):
    return dt.astimezone(EVENT_TIMEZONE).strftime('%H:%M on %B %d %Y')

@register.filter
def idize(s):
    return re.sub('\W+', '_', str(s)).strip('_')

@register.filter
def maybe_red(amount, comp):
    if amount >= comp:
        return SafeString('<span style="color:red ; font-weight:bold">{}</span>'.format(amount))
    else:
        return amount

@register.filter
def maybe_last_year(day):
    return 'last year' if day <= STAFFERS_IMPORTED else day

@register.filter
def join_and(xs):
    if len(xs) in [0, 1, 2]:
        return ' and '.join(xs)
    else:
        xs = xs[:-1] + ['and ' + xs[-1]]
        return ', '.join(xs)

@tag
class maybe_anchor(template.Node):
    def __init__(self, name):
        self.name = Variable(name)

    def render(self, context):
        name = self.name.resolve(context)
        letter = name.upper()[0]
        if letter != context.get('letter'):
            context["letter"] = letter
            return '<a name="{}"></a>'.format(letter)
        else:
            return ""

@tag
class zebra(template.Node):
    counters = local()

    def __init__(self, name, param=''):
        self.name, self.param = name, param

    def render(self, context):
        counter = getattr(self.counters, self.name, 0)
        if self.param == 'start':
            counter = 0
        elif self.param != 'noinc':
            counter = (counter + 1) % 2
        setattr(self.counters, self.name, counter)
        return ['#ffffff','#eeeeee'][counter]

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
                if isinstance(default, datetime):
                    default = default.astimezone(EVENT_TIMEZONE)
            except:
                default = ''

        results = []
        for opt in options:
            if len(listify(opt)) == 1:
                opt = [opt, opt]
            val, desc = opt
            if isinstance(val, datetime):
                selected = 'selected' if val == default else ''
                val = val.strftime(TIMESTAMP_FORMAT)
            else:
                selected = "selected" if str(val) == str(default) else ''
            val  = str(val).replace('"',  '&quot;').replace('\n', '')
            desc = str(desc).replace('"', '&quot;').replace('\n', '')
            results.append('<option value="{}" {}>{}</option>'.format(val, selected, desc))
        return '\n'.join(results)

@tag
class checkbox(template.Node):
    def __init__(self, field):
        model, self.field_name = field.split('.')
        self.model = Variable(model)

    def render(self, context):
        model = self.model.resolve(context)
        checked = 'checked' if getattr(model, self.field_name) else ''
        return '<input type="checkbox" name="{}" value="1" {} />'.format(self.field_name, checked)

@tag
class checkgroup(template.Node):
    def __init__(self, field):
        model, self.field_name = field.split('.')
        self.model = Variable(model)

    def render(self, context):
        model = self.model.resolve(context)
        options = model.get_field(self.field_name).type.choices
        defaults = getattr(model, self.field_name, None)
        defaults = defaults.split(",") if defaults else []
        results = []
        for num, desc in options:
            checked = 'checked' if str(num) in defaults else ''
            results.append('<label class="checkbox-inline"><input type="checkbox" name="{}" value="{}" {} /> {}</label>'
                           .format(self.field_name, num, checked, desc))
        return (''.join(results))

@tag
class int_options(template.Node):
    def __init__(self, minval, maxval, default="1"):
        self.minval  = int(minval) if minval.isdigit() else Variable(minval)
        self.maxval  = int(maxval) if maxval.isdigit() else Variable(maxval)
        self.default = int(default) if default.isdigit() else Variable(default)

    def render(self, context):
        minval = self.minval if isinstance(self.minval, int) else self.minval.resolve(context)
        maxval = self.maxval if isinstance(self.maxval, int) else self.maxval.resolve(context)
        try:
            default = self.default if isinstance(self.default, int) else int(self.default.resolve(context))
        except:
            default = 1

        results = []
        for i in range(minval, maxval+1):
            selected = 'selected' if i==default else ''
            results.append('<option value="{val}" {selected}>{val}</option>'.format(val=i, selected=selected))
        return '\n'.join(results)

@tag
class radio(template.Node):
    def __init__(self, name, value, default):
        self.name    = name[1:-1]
        self.value   = Variable(value)
        self.default = Variable(default)

    def render(self, context):
        value   = self.value.resolve(context)
        default = self.default.resolve(context)
        checked = 'checked' if str(value)==str(default) else ''

        return """<div class="radio"><input type="radio" name="%s" value="%s" %s /></div>""" % (self.name, value, checked)

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

    @staticmethod
    def pretty(model, minute_increment=60):
        minutestr = lambda dt: ':30' if dt.minute == 30 else ''
        endtime   = model.start_time_local + timedelta(minutes = minute_increment * model.duration)
        startstr  = model.start_time_local.strftime('%I').lstrip('0') + minutestr(model.start_time_local)
        endstr    = endtime.strftime('%I').lstrip('0') + minutestr(endtime) + endtime.strftime('%p').lower()

        if model.start_time_local.day == endtime.day:
            endstr += endtime.strftime(' %A')
            if model.start_time_local.hour<12 and endtime.hour>=12:
                return startstr + 'am - ' + endstr
            else:
                return startstr + '-' + endstr
        else:
            return startstr + model.start_time_local.strftime('pm %a - ') + endstr + endtime.strftime(' %a')

    def render(self, context):
        return self.pretty(self.model.resolve(context))

@tag
class popup_link(template.Node):
    def __init__(self, href, text='"<sup>?</sup>"'):
        self.href = href.strip('"')
        self.text = text.strip('"')

    def render(self, context):
        return """<a onClick="window.open('{self.href}', 'info', 'toolbar=no,height=500,width=375,scrollbars=yes').focus(); return false;"
                     href="{self.href}">{self.text}</a>""".format(self=self)

@tag
class must_contact(template.Node):
    def __init__(self, staffer):
        self.staffer = Variable(staffer)

    def render(self, context):
        staffer = self.staffer.resolve(context)
        chairs = defaultdict(list)
        for dept, head in DEPT_CHAIR_OVERRIDES.items():
            chairs[dept].append(head)
        for head in staffer.session.query(Attendee).filter_by(ribbon=DEPT_HEAD_RIBBON).order_by('badge_num').all():
            for dept in head.assigned_depts_ints:
                chairs[dept].append(head.full_name)

        locations = [s.job.location for s in staffer.shifts]
        dept_names = dict(JOB_LOCATION_OPTS)
        return '<br/>'.join(sorted({'({}) {}'.format(dept_names[dept], ' / '.join(chairs[dept])) for dept in locations}))

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
                path = cherrypy.request.request_line.split()[1].split('/')[-1]
                page_qs = 'page={}'.format(pagenum)
                if 'page=' in path:
                    path = re.sub(r'page=\d+', page_qs, path)
                else:
                    path += ('&' if '?' in path else '?') + page_qs
                pages.append('<a href="{}">{}</a>'.format(path, pagenum))
        return 'Page: ' + ' '.join(map(str, pages))

def extract_fields(what):
    if isinstance(what, Attendee):
        return 'a{}'.format(what.id), what.full_name, what.total_cost
    elif isinstance(what, Group):
        return 'g{}'.format(what.id), what.name, what.amount_unpaid
    else:
        return None, None, None

@tag
class nav_menu(template.Node):
    def __init__(self, inst, *items):
        self.inst = Variable(inst)
        self.menu_items = []
        for i in range(0, len(items), 3):
            href, label, display = items[i : i + 3]
            self.menu_items.append([href[1:-1], label[1:-1], display])

    def is_visible(self, display, context):
        bools = {'True': True, 'False': False}
        return bools[display] if display in bools else Variable(display).resolve(context)

    def render(self, context):
        inst = self.inst.resolve(context)
        if inst.is_new:
            return ''

        pages = [(href.format(**inst.__dict__), label)
                 for href, label, display in self.menu_items
                 if self.is_visible(display, context)]

        width = 100 // len(pages)
        items = ['<table class="menu"><tr>']
        for href, label in pages:
            if cherrypy.request.path_info.endswith(href.split('?')[0]):
                link = label
            else:
                link = '<a href="{}">{}</a>'.format(href, label)
            items.append('<td width="{}%">{}</td>'.format(width, link))
        return '\n'.join(items + ['</tr></table>'])

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
        image = 'checked' if checked else 'unchecked'
        return '<img src="../static/images/checkbox_{}.png" style="vertical-align:top ; margin-right:5px" height="20" width="20" />'.format(image)


@tag
class csrf_token(template.Node):
    def render(self, context):
        if not cherrypy.session.get('csrf_token'):
            cherrypy.session['csrf_token'] = uuid4().hex
        return '<input type="hidden" name="csrf_token" value="{}" />'.format(cherrypy.session["csrf_token"])


@tag
class stripe_button(template.Node):
    def __init__(self, *label):
        self.label = ' '.join(label).strip('"')

    def render(self, context):
        return """
            <button class="stripe-button-el">
                <span class="display: block; min-height: 30px;">{label}</span>
            </button>
        """.format(label = self.label)

@tag
class stripe_form(template.Node):
    def __init__(self, action, charge):
        self.action = action
        self.charge = Variable(charge)

    def render(self, context):
        payment_id = uuid4().hex
        charge = self.charge.resolve(context)
        cherrypy.session[payment_id] = charge.to_dict()

        email = ""
        if charge.targets:
            email = charge.models[0].email[:255]

        if not charge.targets:
            regtext = 'On-Site Charge'
        elif AT_THE_CON:
            regtext = 'Registration'
        else:
            regtext = 'Preregistration'

        params = {
            'action': self.action,
            'regtext': regtext,
            'email': email,
            'payment_id': payment_id,
            'charge': charge
        }

        return render('preregistration/stripeForm.html', params)



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
            return '<b>' + output + '</b>'
        else:
            return output

@tag
class organization_and_event_name(template.Node):
    def render(self, context):
        if EVENT_NAME.lower() != ORGANIZATION_NAME.lower():
            return EVENT_NAME + ' and ' + ORGANIZATION_NAME
        else:
            return EVENT_NAME

@tag
class organization_or_event_name(template.Node):
    def render(self, context):
        if EVENT_NAME.lower() != ORGANIZATION_NAME.lower():
            return EVENT_NAME + ' or ' + ORGANIZATION_NAME
        else:
            return EVENT_NAME

@tag
class single_day_prices(template.Node):
    def render(self, context):
        prices = ''
        for day, price in BADGE_PRICES['single_day'].items():
            prices += '${} for {}, '.format(price, day)
        return prices + 'and ${} for other days'.format(BADGE_PRICES['default_single_day'])

class Notice(template.Node):
    def notice(self, label, takedown, discount=False, amount_extra=0):
        discount = BADGE_PRICES['group_discount'] if discount else 0
            
        for day, price in sorted(PRICE_BUMPS.items()):
            if localized_now() < day:
                return 'Price goes up to ${} at 11:59pm EST on {}'.format(price + amount_extra - discount, (day - timedelta(days=1)).strftime('%A, %b %e'))
        else:
            return '{} closes at 11:59pm EST on {}'.format(label, takedown.strftime('%A, %b %e'))

@tag
class attendee_price_notice(Notice):
    def render(self, context):
        return self.notice('Preregistration', PREREG_TAKEDOWN)

@tag
class group_price_notice(Notice):
    def render(self, context):
        return self.notice('Group preregistration', GROUP_PREREG_TAKEDOWN, discount=True)
        
@tag
class supporter_price_notice(Notice):
    def render(self, context):
        return self.notice('Supporter preregistration', SUPPORTER_DEADLINE, amount_extra=SUPPORTER_LEVEL)
        
@tag
class season_price_notice(Notice):
    def render(self, context):
        return self.notice('Season supporter preregistration', SUPPORTER_DEADLINE, amount_extra=SEASON_LEVEL)


template.builtins.append(register)
