import re

from importlib import import_module
from markupsafe import Markup
from wtforms import Form, StringField, IntegerField, BooleanField, validators
import wtforms.widgets.core as wtforms_widgets
from wtforms.validators import Optional, ValidationError, StopValidation
from pockets.autolog import log
from uber.config import c
from uber.forms.widgets import *
from uber.model_checks import invalid_zip_code


def load_forms(params, model, module, form_list):
    # Utility function for initializing several Form objects, since most form pages use multiple Form classes
    # Each class is assigned to a snake_case class name in the return dict,
    # e.g., the PersonalInfo object will be in form_dict['personal_info']
    form_dict = {}
    for cls in form_list:
        form_dict[re.sub(r'(?<!^)(?=[A-Z])', '_', cls).lower()] = getattr(module, cls)(params, model)
    return form_dict


class MagForm(Form):
    skip_unassigned_placeholder_validators = {}

    @classmethod
    def all_forms(cls):
        # Get a list of all forms that inherit from MagForm
        for subclass in cls.__subclasses__():
            yield from subclass.all_forms()
            yield subclass

    @classmethod
    def form_mixin(cls, form, model_str=''):
        if form.__name__ == 'FormMixin':
            target = getattr(cls, form.__name__)
        elif not model_str:
            # Search through all form classes, only continue if there is ONE matching form
            match_count = 0
            for target in cls.all_forms():
                if target.__name__ == form.__name__:
                    match_count += 1
                    real_target = target
            if match_count == 0:
                raise ValueError('Could not find a form with the name {}'.format(form.__name__))
            elif match_count > 1:
                raise ValueError('There is more than one form with the name {}. Please specify which model this form is for.'.format(form.__name__))
            target = real_target
        else:
            # Directly grab the right form from the appropriate module, if it exists
            module = import_module('.' + model_str, 'uber.forms')
            try:
                target = getattr(module, form.__name__)
            except AttributeError:
                raise ValueError('No existing form in the uber.forms.{} module with the name {}'.format(model_str, form.__name__))

        for name in dir(form):
            if not name.startswith('_'):
                setattr(target, name, getattr(form, name))
        return target

    def __init__(self, formdata=None, obj=None, prefix='', data=None, meta=None, **kwargs):
        meta_obj = self._wtforms_meta()
        if meta is not None and isinstance(meta, dict):
            meta_obj.update_values(meta)
        super(Form, self).__init__(self._unbound_fields, meta=meta_obj, prefix=prefix)
        
        # Special form data preprocessing!
        #
        # WTForms is supposed to use data from obj if it's not present in formdata
        # but a bug prevents this from working for boolean fields so let's do it ourselves
        #
        # We also convert our MultiChoice value (a string) into the list of strings that WTForms expects
        for name, field in self._fields.items():
            field_in_obj = hasattr(obj, name)
            field_in_formdata = name in formdata
            if isinstance(field, BooleanField) and not field_in_formdata and field_in_obj:
                formdata[name] = getattr(obj, name)
            elif hasattr(obj, 'all_checkgroups') and not field_in_formdata and field_in_obj and name in obj.all_checkgroups:
                formdata[name] = getattr(obj, name).split(',')

        super().__init__(formdata, obj, prefix, data, meta, **kwargs)

    def field_list(self):
        return list(self._fields.keys())


    class Meta:
        text_vars = {
            'EVENT_NAME': c.EVENT_NAME,
            'EVENT_YEAR': c.EVENT_YEAR,
            'ORGANIZATION_NAME': c.ORGANIZATION_NAME,
            }

        def get_field_type(self, field):
            # Returns a key telling our Jinja2 form input macro how to render the scaffolding based on the widget

            widget = field.widget
            if isinstance(widget, SwitchInput):
                return 'switch'
            elif isinstance(widget, wtforms_widgets.CheckboxInput):
                return 'checkbox'
            elif isinstance(widget, (NumberInputGroup, DollarInput)):
                return 'inputgroup'
            elif isinstance(widget, MultiCheckbox):
                return 'checkgroup'
            elif isinstance(widget, wtforms_widgets.Select):
                return 'select'
            else:
                return 'text'

        def bind_field(self, form, unbound_field, options):
            """
            This function implements all our custom logic to apply to fields upon init. Currently, we:
            - Get a label and description override from a function on the form class, if there is one
            - Format label and description text to process common variables
            - Add default rendering keywords to make fields function better in our forms
            """
            field_name = options.get('name', '')
            text_format_vars = {**getattr(form, 'extra_text_vars', {}), **self.text_vars}
            field_label = self.get_override_attr(form, field_name, '_label') or unbound_field.kwargs.get('label', '') or unbound_field.args[0]
            field_desc = self.get_override_attr(form, field_name, '_desc') or unbound_field.kwargs.get('description', '')

            if 'label' in unbound_field.kwargs:
                unbound_field.kwargs['label'] = self.format_field_text(field_label, text_format_vars)
            elif unbound_field.args and isinstance(unbound_field.args[0], str):
                args_list = list(unbound_field.args)
                args_list[0] = self.format_field_text(field_label, text_format_vars)
                unbound_field.args = tuple(args_list)

            if field_desc:
                unbound_field.kwargs['description'] = self.format_field_text(field_desc, text_format_vars)
            
            unbound_field.kwargs['render_kw'] = self.set_keyword_defaults(unbound_field, unbound_field.kwargs.get('render_kw', {}), field_name)

            return unbound_field.bind(form=form, **options)

        def get_override_attr(self, form, field_name, suffix):
            return getattr(form, field_name + suffix, lambda: '')()

        def format_field_text(self, text, format_vars):
            # Formats label text and descriptions to allow common config values to be included in the class declaration
            was_markup = isinstance(text, Markup)
            formatted_text = str(text).format(**format_vars)
            
            if was_markup:
                return Markup(formatted_text)
            return formatted_text

        def set_keyword_defaults(self, ufield, render_kw, field_name):
            # Changes the render_kw dictionary to implement some high-level defaults

            # Fixes textarea fields to work with Bootstrap floating labels
            widget = ufield.kwargs.get('widget', None) or ufield.field_class.widget
            if isinstance(widget, wtforms_widgets.TextArea):
                if 'rows' in render_kw:
                    pixels = int(render_kw['rows']) * 30
                else:
                    pixels = 90
                if 'style' in render_kw:
                    render_kw['style'] += "; "
                render_kw['style'] = render_kw.get('style', '') + "height: {}px".format(pixels)
            
            # Floating labels need the placeholder set in order to work, so add one if it does not exist
            if 'placeholder' not in render_kw:
                render_kw['placeholder'] = " "

            # Support for validating fields inline
            render_kw['aria-describedby'] = field_name + "-validation"

            return render_kw

        def wrap_formdata(self, form, formdata):
            # Auto-wraps param dicts in a multi-dict wrapper for WTForms
            if isinstance(formdata, dict):
                formdata = DictWrapper(formdata)

            return super().wrap_formdata(form, formdata)


class AddressForm():
    address1 = StringField('Address Line 1', default='', validators=[validators.InputRequired(message="Please enter a street address.")])
    address2 = StringField('Address Line 2', default='')
    city = StringField('City', default='', validators=[validators.InputRequired(message="Please enter a city.")])
    region = StringField('State/Province', default='')
    zip_code = StringField('Zip/Postal Code', default='')
    country = StringField('Country', default='', validators=[validators.InputRequired(message="Please enter a country.")])

    def validate_region(form, field):
        if form.country.data in ['United States', 'Canada'] and not field.data:
            raise ValidationError('Please enter a state, province, or region.')
    
    def validate_zip_code(form, field):
        if form.country.data == 'United States' and not c.AT_OR_POST_CON and invalid_zip_code(field.data):
            raise ValidationError('Please enter a valid 5 or 9-digit zip code.')


class HiddenIntField(IntegerField):
    widget = wtforms_widgets.HiddenInput()


class DictWrapper(dict):
    def getlist(self, arg):
        if arg in self:
            if isinstance(self[arg], list):
                return self[arg]
            else:
                return [self[arg]]
        else:
            return []


from uber.forms.attendee import *  # noqa: F401,E402,F403
