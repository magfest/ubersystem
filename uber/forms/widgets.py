from markupsafe import escape, Markup
from wtforms.widgets import NumberInput, html_params, CheckboxInput, TextInput, Select
from uber.config import c
from uber.custom_tags import linebreaksbr


class MultiCheckbox():
    """
    Renders a MultiSelect field as a set of checkboxes, e.g., "What interests you?"
    """
    def __call__(self, field, **kwargs):
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
            if 'readonly' in kwargs:
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



class UniqueList(TextInput):
    """
    There are two ways to handle a UniqueList column: a single string field for use with Tagify,
    or a set of string fields. This widget handles both.
    """

    def __call__(self, field, num_fields=2, **kwargs):
        if num_fields == 1:
            super().__call__(field, **kwargs)

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
                    <div class="d-flex justify-content-between">
                    <h4 class="card-title {'mb-0' if not extra_info else 'mb-1 mb-sm-2'}">
                        {choice_item["name"]}
                    </h4>
                    <div>
                        <i class="fa fa-arrow-circle-up move-up-{id}" data-direction="up" tabindex="0"></i>
                        <i class="fa fa-arrow-circle-down move-down-{id}" data-direction="down" tabindex="0"></i>
                    </div>
                    </div>""")
                selected_html.extend(extra_info)
                selected_html.append(f"""
                    <div class="d-flex gap-1 justify-content-end">
                        <input type="hidden" name="{id}" value="{choice_id}">
                        <i class="fa fa-minus-circle text-danger deselect-{id}" tabindex="0"></i>
                        <i class="fa fa-plus-circle text-success select-{id}" tabindex="0" style="display:none;"></i>
                    </div>
                </li>""")
            except KeyError:
                continue
        for choice_id, choice_item in choices:
            if not choice_id in selected_choices:
                extra_info = self.extra_info_list(choice_item, show_staff_rates=show_staff_rates)
                deselected_html.append(f"""
                <li class="card card-body border-dark p-2 p-sm-3 sortable-item" data-choice="{choice_id}" value="{choice_id}">
                    <div class="d-flex justify-content-between">
                    <h4 class="card-title {'mb-0' if not extra_info else 'mb-1 mb-sm-2'}">
                        {choice_item["name"]}
                    </h4>
                    <div>
                        <i class="fa fa-arrow-circle-up move-up-{id}" data-direction="up" tabindex="0"></i>
                        <i class="fa fa-arrow-circle-down move-down-{id}" data-direction="down" tabindex="0"></i>
                    </div>
                    </div>""")
                deselected_html.extend(extra_info)
                deselected_html.append(f"""
                    <div class="d-flex gap-1 justify-content-end">
                        <input type="hidden" value="{choice_id}">
                        <i class="fa fa-minus-circle text-danger deselect-{id}" tabindex="0" style="display:none;"></i>
                        <i class="fa fa-plus-circle text-success select-{id}" tabindex="0"></i>
                    </div>
                </li>""")

        script = f"""
        <script type="text/javascript">
            var showOrHidePlaceholders_{ id } = function(select_or_deselect) {{
                let ulOpts = document.getElementById(select_or_deselect + "ed_{ id }");
                if (ulOpts.children.length == 0) {{
                    ulOpts.classList.add('placeholder-'+ select_or_deselect +'-opt');
                }} else {{
                    ulOpts.classList.remove('placeholder-'+ select_or_deselect +'-opt');
                }}
            }}

            var deselected_list_{id} = Sortable.create(deselected_{ id }, {{
                group: '{ id }',
                animation: 100,
                dataIdAttr: 'data-choice',
            }});

            var selected_list_{id} = Sortable.create(selected_{ id }, {{
                group: '{ id }',
                animation: 100,
                dataIdAttr: 'data-choice',
                onSort: function(evt) {{
                    el = document.getElementById("selected_{ id }");
                    showOrHidePlaceholders_{ id }("select");
                    for (let i=0; i<el.children.length; i++) {{
                        el.children[i].querySelector(".select").style.display = 'none';
                        el.children[i].querySelector(".deselect").style.display = 'block';
                        el.children[i].querySelector("input").setAttribute("name", "{ id }");
                    }}

                    dl = document.getElementById("deselected_{ id }");
                    showOrHidePlaceholders_{ id }("deselect");
                    for (let i=0; i<dl.children.length; i++) {{
                        dl.children[i].querySelector(".select").style.display = 'block';
                        dl.children[i].querySelector(".deselect").style.display = 'none';
                        dl.children[i].querySelector("input").removeAttribute("name");
                    }}
                    
                }}
            }});

            var listItemSelector = 'li.sortable-item';

            var moveElement_{id} = function(element, direction) {{
                if (typeof(element.dataset.choice) == 'undefined') {{
                    return false
                }}

                let sortable_list;

                if (element.closest('ul').id.includes('deselected')) {{
                    sortable_list = deselected_list_{id};
                }} else {{
                    sortable_list = selected_list_{id};
                }}
                
                // `sortableId` is whatever you've set in your sortablejs config for `dataIdAttr`
                let sortableId = element.dataset.choice
                let order = sortable_list.toArray()
                let index = order.indexOf(sortableId)
                
                // pull the item we're moving out of the order
                order.splice(index, 1)
                
                // put it back in at the correct position
                if (direction == 'down') {{
                    order.splice(index+1, 0, sortableId)
                }} else if (direction == 'up') {{
                    order.splice(index-1, 0, sortableId)
                }}

                sortable_list.sort(order, true)
            }}

            var arrowButton_{id} = function(event) {{
                direction = event.currentTarget.dataset.direction
                otherButton = direction == 'down' ? 'up' : 'down'

                if (event && (event.key == "Enter" || event.screenX && event.screenY)) {{
                    this.moveElement_{id}(event.currentTarget.closest(listItemSelector), direction)
                    if (window.getComputedStyle(event.currentTarget).display == 'none') {{
                    event.currentTarget.parentNode.querySelector(`i[data-direction={{otherButton}}]`).focus()
                    }} else {{
                    event.currentTarget.focus()
                    }}
                }}
            }}

            var addOrRemove_{id} = function(element, oldList, newList) {{
                if (typeof(element.dataset.choice) == 'undefined') {{
                    return false;
                }}

                let sortableId = element.dataset.choice;
                let oldOrder = oldList.toArray()
                let newOrder = newList.toArray()
                let newElement = Sortable.utils.clone(element)
                console.log(newElement)

                // pull the item we're moving out of the order
                oldOrder.splice(index, 1)

                // ...and into the new list
                newOrder.splice(index, 0, sortableId);

                oldList.sort(oldOrder, true);
                newList.sort(newOrder, true);
            }}

            var addButton_{id} = function(event) {{
                if (event && (event.key == "Enter" || event.screenX && event.screenY)) {{
                    addOrRemove_{id}(event.currentTarget.closest(listItemSelector), deselected_list_{id}, selected_list_{id});
                }}
            }}

            var removeButton_{id} = function(event) {{
                if (event && (event.key == "Enter" || event.screenX && event.screenY)) {{
                    addOrRemove_{id}(event.currentTarget.closest(listItemSelector), selected_list_{id}, deselected_list_{id});
                }}
            }}

            $().ready(function() {{
                showOrHidePlaceholders_{id}("select");
                showOrHidePlaceholders_{id}("deselect");
                $('.move-up-{id}').bind('click keydown', function() {{ arrowButton_{id}(event) }});
                $('.move-down-{id}').bind('click keydown', function() {{ arrowButton_{id}(event) }});
                $('.select-{id}').bind('click keydown', function() {{ addButton_{id}(event) }});
                $('.deselect-{id}').bind('click keydown', function() {{ removeButton_{id}(event) }});
            }});
        </script>"""

        if read_only:
            html = []
        else:
            html = ['<div class="row">']

        if not read_only:
            html.extend([
                '<div class="col-sm-6">',
                f'<span class="form-text">Available {field.label.text}</span>',
                f'<ul class="card card-body bg-light gap-2 p-2 p-sm-3" id="deselected_{id}">',
                *deselected_html,
                '</ul></div>'
                ])
        html.extend([
            '<div class="col-sm-6">',
            f'<span class="form-text">{'' if read_only else 'Selected '}{field.label.text} <em>(ranked top to bottom)</em></span>',
            f'<ul class="card card-body bg-light gap-2 p-2 p-sm-3" id="selected_{id}">',
            *selected_html,
            f'</ul></div>',
            script if not read_only else ''
            ])

        if not read_only:
            html.append('</div>')

        return Markup(''.join(html))