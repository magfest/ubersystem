import six
import logging
from dateutil import parser as dateparser

from markupsafe import escape, Markup
from wtforms.widgets import NumberInput, html_params, CheckboxInput, TextInput, Select, HiddenInput
from uber.config import c
from uber.custom_tags import linebreaksbr

log = logging.getLogger(__name__)


class MultiCheckbox():
    """
    Renders a MultiSelect field as a set of checkboxes, e.g., "What interests you?"
    """
    def __call__(self, field, choices=None, **kwargs):
        choices = choices or field.choices
        field.choices = choices

        kwargs.setdefault('type', 'checkbox')
        field_id = kwargs.pop('id', field.id)
        html = []
        for value, label, checked, _html_attribs in field.iter_choices():
            choice_id = '{}-{}'.format(field_id, value)
            options = dict(kwargs, name=field.name, value=value, id=choice_id)
            if 'readonly' in options:
                options['disabled'] = True
            if checked:
                options['checked'] = 'checked'
            html.append('<label for="{}" class="checkbox-label">'.format(choice_id))
            html.append('<input {} /> '.format(html_params(**options)))
            html.append('{}</label>'.format(label))
        return Markup(''.join(html))


class IntSelect():
    """
    Renders an Integer or Decimal field as a select dropdown, e.g., the "badges" dropdown for groups.
    The list of choices can be provided on init or during render and should be a list of (value, label) tuples.
    Note that choices must include a null/zero option if you want one.
    """
    def __init__(self, choices=None, **kwargs):
        self.choices = choices

    def __call__(self, field, choices=None, **kwargs):
        choices = choices or self.choices or [('', "ERROR: No choices provided")]
        field_id = kwargs.pop('id', field.id)
        options = dict(kwargs, id=field_id, name=field.name)
        if 'readonly' in options:
            options['disabled'] = True
        html = ['<select class="form-select" {}>'.format(html_params(**options))]
        for value, label in choices:
            choice_id = '{}-{}'.format(field_id, value)
            choice_options = dict(value=value, id=choice_id)
            if value == field.data:
                choice_options['selected'] = 'selected'
            html.append('<option value="{}" {}>{}</option>'.format(value, html_params(**choice_options), label))
        html.append('</select>')
        return Markup(''.join(html))


# Dummy class for our Jinja2 macros -- switches in Bootstrap are set in the scaffolding, not on the input
class SwitchInput(CheckboxInput):
    pass


class SelectButtonGroup(Select):
    def __init__(self, multiple=False):
        self.multiple = multiple
        self.default_opt_kwargs = {
            'type': 'checkbox' if self.multiple else 'radio',
            'btn_cls': 'btn-outline-secondary',
        }

    @classmethod
    def render_option(cls, value, label, selected, **kwargs):
        if value is True:
            value = "true"

        options = dict(kwargs, value=value)
        btn_cls = options.pop('btn_cls', 'btn-outline-secondary')
        if selected:
            options['checked'] = True
        html = [f'<input class="btn-check" autocomplete="off" {html_params(**options)}>']
        html.append(f'<label class="btn {btn_cls}" for="{options['id']}">{escape(label)}</label>')
        return ''.join(html)

    def __call__(self, field, **kwargs):
        kwargs.setdefault('id', field.id)

        if 'required' not in kwargs and 'required' in getattr(field, 'flags', []):
            kwargs['required'] = True

        html = ['<div class="btn-group" role="group">']
        for value, label, selected, render_kw in field.iter_choices():
            options = {
                'id': f"{kwargs['id']}-{value}",
                'name': field.name,
                **self.default_opt_kwargs
                }
            if 'readonly' in kwargs and kwargs['readonly']:
                options['disabled'] = True
            options.update(render_kw)
            for opt, val in kwargs.items():
                if opt.startswith('x-'):
                    options[opt] = val
            html.append(self.render_option(value, label, selected, **options))
        html.append('</div>')
        return Markup(''.join(html))


class SelectDynamicChoices(Select):
    def __call__(self, field, choices=None, **kwargs):
        choices = choices or [('', "ERROR: No choices provided")]
        field.choices = choices
        return super().__call__(field, **kwargs)


class NumberInputGroup(TextInput):
    def __init__(self, prefix='$', suffix='.00', **kwargs):
        self.prefix = prefix
        self.suffix = suffix
        super().__init__(**kwargs)

    def __call__(self, field, **kwargs):
        html = []
        if self.prefix:
            html.append('<span class="input-group-text">{}</span>'.format(self.prefix))
        html.append(super().__call__(field, **kwargs))
        if self.suffix:
            html.append('<span class="input-group-text rounded-end">{}</span>'.format(self.suffix))

        return Markup(''.join(html))


class DateMaskInput(TextInput):
    def __call__(self, field, **kwargs):
        script = """
        <script type="text/javascript">
        if(!dateFormat) {
            function dateFormat(input) {
                const first_month = input.substring(0, 1);
                if ((/^-?\d+$/.test(first_month)) == false) {
                return '99/99/9999';
                }
                if (!['0','1'].includes(first_month)) {
                return '0' + input + '/99/9999';
                }
                if (input.length == 4 && input.substring(2, 3) == '/') {
                const first_day = input.substring(3, 4);
                if ((/^-?\d+$/.test(first_day)) == false) {
                    return '99/99/9999';
                }
                if (!['0','1','2','3'].includes(first_day)) {
                    return input.substring(0, 3) + '0' + input.substring(3, 4) + '/9999'
                }
                }
                return '99/99/9999';
            }
        }
        </script>
        """
        kwargs['placeholder'] = "MM/DD/YYYY"
        kwargs['x-mask:dynamic'] = "dateFormat"
        html =[script, super().__call__(field,  **kwargs)]
        return Markup(''.join(html))


class DateTimePicker(TextInput):
    def __call__(self, field, min_date=c.SHIFTS_EPOCH, max_date=c.SHIFTS_ESCHATON, start_dt=None, **kwargs):
        id = kwargs.pop('id', field.id) or "date-time-picker"
        start_dt = field.data or start_dt or c.EPOCH
        if isinstance(start_dt, six.string_types):
            start_dt = c.EVENT_TIMEZONE.localize(dateparser.parse(start_dt))
        html = f"""
        <div class="input-group">
            <input id="{id}" name="{field.name}" type="text" class="form-control" value="">
            <span class="input-group-text"><i class="fa fa-calendar"></i></span>
        </div>"""

        script = f"""
        <script type="text/javascript">
            window.eventTimeZone = "{c.EVENT_TIMEZONE}";

            let flatpickrInput{id} = flatpickr('#{id}',{{
                allowInput: true,
                enableTime: true,
                altInput: true,
                altFormat: 'M/D/YYYY  hh:mm A', //use moment format not flatpickr
                disableMobile: true, //Do not let mobile native datepicker take over.
                dateFormat: 'YYYY-MM-DD\\\\THH:mm:ssZ', // use moment formats, not flatpickr
                defaultDate: '{start_dt.isoformat()}',
                minDate: '{min_date.isoformat()}',
                maxDate: '{max_date.isoformat()}',
                parseDate(dateString, format) {{
                    let eventTimezonedDate = new moment.tz(dateString, format, window.eventTimeZone);

                    //Return a date in the *local* timezone that force uses the values as if they were event timezone.
                    return new Date(
                        eventTimezonedDate.year(),
                        eventTimezonedDate.month(),
                        eventTimezonedDate.date(),
                        eventTimezonedDate.hour(),
                        eventTimezonedDate.minute(),
                        eventTimezonedDate.second()
                    );
                }},
                formatDate(date, format) {{
                    let formatted =  moment.tz([
                        date.getFullYear(),
                        date.getMonth(),
                        date.getDate(),
                        date.getHours(),
                        date.getMinutes(),
                        date.getSeconds()
                    ], window.eventTimeZone).format(format);
                    return formatted;
                }}
            }});
        </script>"""
        return Markup(''.join([html, script]))


class HourMinuteDuration(HiddenInput):
    def __call__(self, field, **kwargs):
        id = kwargs.pop('id', field.id)
        duration = int(field.data) if field.data else 0
        hours, minutes = int(duration / 60), int(duration % 60)
        html = f"""
        <div x-data="{{
            hours: {hours},
            minutes: {minutes},
            getTotal() {{ return parseInt(this.hours) * 60 + parseInt(this.minutes) }},
            }}">
            <div class="input-group">
                <input type="number" x-model="hours" class="form-control" onfocus="this.select();" name="{field.name}_hours" placeholder="# hours" value="{hours}" />
                <span class="input-group-text">hours,</span>
                <input type="number" x-model="minutes" class="form-control" onfocus="this.select();" name="{field.name}_minutes" placeholder="# minutes" value="{minutes}" />
                <span class="input-group-text">minutes</span>
            </div>
            <input type="hidden" name="{field.name}" id="{id}" value={duration} x-bind:value="getTotal">
        </div>"""
        return Markup(html)

class UniqueList(TextInput):
    """
    There are two ways to handle a UniqueList column: a single string field with Tagify enabled,
    or a set of string fields. This widget handles both.
    """

    def tagify_js(self, field, choices=None, **kwargs):
        id = kwargs.pop('id', field.id)
        enforce = 'false'
        text_prop = 'value'

        if hasattr(field, 'choices'):
            choices = choices or field.choices
            if isinstance(choices[0], tuple):
                choices = [{'value': choice[0], 'label': choice[1]} for choice in choices]
                text_prop = 'label'
            if hasattr(field, 'validate_choice'):
                enforce = 'true' if field.validate_choice == True else 'false'
        
        return f'''
        <script type="text/javascript">
        $().ready(function () {{
            let input{id} = document.getElementById('{id}');
            tagify{id} = new Tagify(input{id}, {{
                whitelist: {choices},
                tagTextProp: '{text_prop}',
                autoComplete: {{
                    rightKey: true,
                    tabKey: true,
                }},
                dropdown: {{
                    enabled: 0,
                    highlightFirst: true,
                    mapValueTo: '{text_prop}',
                    searchKeys: ['value', '{text_prop}'],
                    enforceWhitelist: {enforce},
                    maxItems: 20,
                    classname: 'tagify-tags-{id}-input',
                    enabled: 0,
                    closeOnSelect: false
                }}
            }})
        }})
        </script>'''

    def __call__(self, field, num_fields=2, whitelist=[], **kwargs):
        if num_fields == 1:
            if not whitelist and not getattr(field, 'choices', None):
                super().__call__(field, value=field.data or '', **kwargs)
            else:
                html = super().__call__(field, value=field.data or '', **kwargs)
                js = Markup(self.tagify_js(field, whitelist, **kwargs))
                return html + js

        choices = field.data.split(',') if field.data else []
        placeholder = kwargs.pop('placeholder', '')

        # Normalize choices length based on num_fields
        choices = choices[:num_fields]
        for _ in range(len(choices), num_fields):
            choices.append('')

        html = ['<div class="d-flex gap-1">']
        for idx, value in enumerate(choices, 1):
            field.data = value
            field_placeholder = f"{placeholder} {idx}" if placeholder else ''
            html.append(super().__call__(field, placeholder=field_placeholder, **kwargs))
        html.append('</div>')
        field.data = ','.join(choices)
        return Markup(''.join(html))


class Ranking():
    def __init__(self, choices=None, **kwargs):
        self.choices = choices
        super().__init__(**kwargs)
    
    def extra_info_list(self, choice_item, show_staff_rates=False):
        # Rankings can have a few properties that are displayed differently, but all of them are optional
        # They can be: price (sub-header), staff_price (sub-header displayed during staff lottery),
        #              description (text), description_right (right-aligned text), footnote (form-text text)
        extra_info = []
        if choice_item.get('price'):
            price_str = f"{choice_item['price']}"
            if show_staff_rates and choice_item.get('staff_price'):
                price_str = price_str + f"/{choice_item['staff_price']}"
            extra_info.append(f"""<h5 class="card-subtitle mb-2 text-muted">{price_str}</h5>""")
        if choice_item.get('description') or choice_item.get('description_right'):
            extra_info.append("""<div class="card-text">""")
            if choice_item.get('description'):
                extra_info.append(linebreaksbr(choice_item["description"]))
            if choice_item.get('description_right'):
                extra_info.append(f"""<br/><span class="pull-right text-end">{linebreaksbr(choice_item["description_right"])}</span>""")
            extra_info.append("""</div>""")
        if choice_item.get('footnote'):
            extra_info.append(f"""<div class="form-text">{linebreaksbr(choice_item["footnote"])}</div>""")
        return extra_info
    
    def __call__(self, field, choices=None, show_staff_rates=False, **kwargs):
        choices = choices or self.choices or [('', {"name": "Error", "description": "No choices are configured"})]
        id = kwargs.pop('id', field.id) or "ranking"
        selected_choices = field.data if isinstance(field.data, list) else [str(field.data)]
        read_only = 'readonly' in kwargs and kwargs['readonly']

        deselected_html = []
        selected_html = []
        choice_dict = {key: val for key, val in choices}
        for choice_id in selected_choices:
            try:
                choice_item = choice_dict[choice_id]
                extra_info = self.extra_info_list(choice_item, show_staff_rates=show_staff_rates)
                selected_html.append(f"""
                <li class="card card-body border-dark p-2 p-sm-3 sortable-item" data-choice="{choice_id}" value="{choice_id}">
                    <div class="d-flex justify-content-between align-items-center">
                    <h4 class="text-muted h5 card-title me-1 {'mb-0' if not extra_info else 'mb-1 mb-sm-2'}">
                        <span class="selected-order"></span> {choice_item["name"]}
                    </h4>
                    <div class="text-end">
                        <button type="button" data-id="{id}" class="fa fa-arrow-circle-up move-up bg-transparent border-0 p-0" data-direction="up" tabindex="0"></button>
                        <button type="button" data-id="{id}" class="fa fa-arrow-circle-down move-down bg-transparent border-0 p-0" data-direction="down" tabindex="0"></button>
                        <button type="button" data-id="{id}" class="fa fa-minus-circle text-danger deselect bg-transparent border-0 p-0" tabindex="0"></button>
                        <button type="button" data-id="{id}" class="fa fa-plus-circle text-success select bg-transparent border-0 p-0" tabindex="0"></button>
                    </div>
                    </div>""")
                selected_html.extend(extra_info)
                selected_html.append(f"""<input type="hidden" name="{id}" value="{choice_id}"></li>""")
            except KeyError:
                continue
        for choice_id, choice_item in choices:
            if not choice_id in selected_choices:
                extra_info = self.extra_info_list(choice_item, show_staff_rates=show_staff_rates)
                deselected_html.append(f"""
                <li class="card card-body border-dark p-2 p-sm-3 sortable-item" data-choice="{choice_id}" value="{choice_id}">
                    <div class="d-flex justify-content-between align-items-center">
                    <h4 class="card-title me-1 {'mb-0' if not extra_info else 'mb-1 mb-sm-2'}">
                        <span class="selected-order"></span> {choice_item["name"]}
                    </h4>
                    <div class="text-end">
                        <button type="button" data-id="{id}" class="fa fa-arrow-circle-up move-up bg-transparent border-0 p-0" data-direction="up" tabindex="0"></button>
                        <button type="button" data-id="{id}" class="fa fa-arrow-circle-down move-down bg-transparent border-0 p-0" data-direction="down" tabindex="0"></button>
                        <button type="button" data-id="{id}" class="fa fa-minus-circle text-danger deselect bg-transparent border-0 p-0" tabindex="0"></button>
                        <button type="button" data-id="{id}" class="fa fa-plus-circle text-success select bg-transparent border-0 p-0" tabindex="0"></button>
                    </div>
                    </div>""")
                deselected_html.extend(extra_info)
                deselected_html.append(f"""<input type="hidden" value="{choice_id}"></li>""")

        script = f"""
        <script type="text/javascript">
            // Initialize the sortable extensions for keyboard accessibility.
            // ID and what your sortable li class are must be passed in.
            SortableExt.initWidget('{id}', 'li.sortable-item');
        </script>"""

        if read_only:
            html = []
        else:
            html = ['<div class="row">']

        html.extend([
            '<div class="col-sm-6">',
            f'<span class="form-text">{'' if read_only else 'Selected '}{field.label.text}</span>',
            f'<ul class="card card-body bg-light gap-2 p-2 p-sm-3" id="selected_{id}">',
            *selected_html,
            f'</ul></div>',
            ])

        if not read_only:
            html.extend([
                '<div class="col-sm-6">',
                f'<span class="form-text">Available {field.label.text}</span>',
                f'<ul class="card card-body bg-light gap-2 p-2 p-sm-3" id="deselected_{id}">',
                *deselected_html,
                '</ul></div>',
                script,
                '</div>',
                ])

        return Markup(''.join(html))