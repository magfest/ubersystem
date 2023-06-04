from markupsafe import Markup
from wtforms.widgets import NumberInput, html_params, CheckboxInput
from uber.config import c

class MultiCheckbox():
    def __call__(self, field, div_class='checkgroup', **kwargs):
        kwargs.setdefault('type', 'checkbox')
        field_id = kwargs.pop('id', field.id)
        html = ['<div %s>' % html_params(id=field_id, class_=div_class)]
        html.append('<fieldset>')
        for value, label, checked in field.iter_choices():
            choice_id = '%s-%s' % (field_id, value)
            options = dict(kwargs, name=field.name, value=value, id=choice_id)
            if value == c.OTHER:
                html.append('<br/>')
            if checked:
                options['checked'] = 'checked'
            html.append('<label for="%s" class="checkbox-label">' % choice_id)
            html.append('<input %s /> ' % html_params(**options))
            html.append('%s</label>' % label)
        html.append('</fieldset>')
        html.append('</div>')
        return Markup(''.join(html))


# Dummy class for get_field_type() -- switches in Bootstrap are set in the scaffolding, not on the input
class SwitchInput(CheckboxInput):
    pass


class NumberInputGroup(NumberInput):
    def __init__(self, prefix='', suffix='', **kwargs):
        self.prefix = prefix
        self.suffix = suffix
        super().__init__(**kwargs)

    def __call__(self, field, **kwargs):
        html = ['<div class="input-group mb-3">']
        if self.prefix:
            html.append('<span class="input-group-text">{}</span>'.format(self.prefix))
        html.append(super().__call__(field, **kwargs))
        if self.suffix:
            html.append('<span class="input-group-text">{}</span>'.format(self.suffix))
        html.append('</div>')

        return Markup(''.join(html))


class DollarInput(NumberInputGroup):
    def __init__(self, prefix='$', suffix='.00', **kwargs):
        super().__init__(prefix, suffix, **kwargs)