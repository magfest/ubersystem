import re
import cherrypy

from importlib import import_module
from markupsafe import Markup
from wtforms import Form, StringField, SelectField, IntegerField, BooleanField, validators
import wtforms.widgets.core as wtforms_widgets
from wtforms.validators import Optional, ValidationError, StopValidation
from pockets.autolog import log
from uber.config import c
from uber.forms.widgets import *
from uber.model_checks import invalid_zip_code


def load_forms(params, model, module, form_list, prefix_dict={}):
    """
    Utility function for initializing several Form objects, since most form pages use multiple Form classes.

    Also adds aliases for common fields, e.g., mapping the `region` column to `region_us` and `region_canada`.
    This is currently only designed to work with text fields and select fields with a [(val, label)] list of choices.

    `params` should be a dictionary from a form submission, usually passed straight from the page handler.
    `model` is the object itself, e.g., the attendee we're loading the form for.
    `form_list` is a list of strings of which form classes to load, e.g., ['PersonalInfo', 'BadgeExtras', 'OtherInfo']
    `prefix_dict` is an optional dictionary to load some of the forms with a prefix. This is useful for loading forms with
    conflicting field names on the same page, e.g., passing {'GroupInfo': 'group_'} will add group_ to all GroupInfo fields.

    Returns a dictionary of form objects with the snake-case version of the form as the ID, e.g.,
    the PersonalInfo class will be returned as form_dict['personal_info'].
    """

    form_dict = {}
    alias_dict = {}

    for cls in form_list:
        form_cls = getattr(module, cls, None)
        if not form_cls:
            break

        for model_field_name, aliases in form_cls.field_aliases.items():
            model_val = getattr(model, model_field_name)
            for aliased_field in aliases:
                aliased_field_args = getattr(form_cls, aliased_field).kwargs
                choices = aliased_field_args.get('choices')
                if choices:
                    alias_dict[aliased_field] = model_val if model_val in [val for val, label in choices] else aliased_field_args.get('default')
                else:
                    alias_dict[aliased_field] = model_val

        form_dict[re.sub(r'(?<!^)(?=[A-Z])', '_', cls).lower()] = form_cls(params, model, prefix=prefix_dict.get(cls, ''), data=alias_dict)
    return form_dict


class MagForm(Form):
    field_aliases = {}

    def get_optional_fields(self, model):
        return []

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
        # Checkboxes aren't submitted in HTML forms if they're unchecked; additionally, there is a bug in WTForms
        # So if a checkbox isn't present in the params, we use the object's value UNLESS this form was submitted,
        # in which case we set it to false
        #
        # We also convert our MultiChoice value (a string) into the list of strings that WTForms expects
        for name, field in self._fields.items():
            field_in_obj = hasattr(obj, name)
            field_in_formdata = name in formdata
            if isinstance(field, BooleanField) and not field_in_formdata and field_in_obj:
                if cherrypy.request.method == 'POST':
                    formdata[name] = False
                else:
                    formdata[name] = getattr(obj, name)
            elif hasattr(obj, 'all_checkgroups') and not field_in_formdata and field_in_obj and \
                name in obj.all_checkgroups and isinstance(getattr(obj, name), str):
                formdata[name] = getattr(obj, name).split(',')

        super().__init__(formdata, obj, prefix, data, meta, **kwargs)

    @property
    def field_list(self):
        return list(self._fields.items())
    
    @property
    def bool_list(self):
        return [(key, field) for key, field in self._fields.items() if field.type == 'BooleanField']
    
    def populate_obj(self, obj):
        """ Adds alias processing and data coercion to populate_obj. Note that we bypass fields' populate_obj. """
        for name, field in self._fields.items():
            column = obj.__table__.columns.get(name)
            if column is not None:
                setattr(obj, name, obj.coerce_column_data(column, field.data))
            else:
                try:
                    setattr(obj, name, field.data)
                except AttributeError:
                    pass # Probably just a collision between a property name and a form field name, e.g., 'badges' for GroupInfo

        for model_field_name, aliases in self.field_aliases.items():
            for aliased_field in reversed(aliases):
                field_obj = getattr(self, aliased_field, None)
                if field_obj and field_obj.data:
                    field_obj.populate_obj(obj, model_field_name)


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
            elif isinstance(widget, CountrySelect):
                return 'text'
            elif isinstance(widget, wtforms_widgets.Select):
                return 'select'
            elif isinstance(widget, IntSelect):
                return 'customselect'
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
    field_aliases = {'region': ['region_us', 'region_canada']}

    address1 = StringField('Address Line 1', default='', validators=[
        validators.InputRequired(message="Please enter a street address.")
        ])
    address2 = StringField('Address Line 2', default='')
    city = StringField('City', default='', validators=[
        validators.InputRequired(message="Please enter a city.")
        ])
    region_us = SelectField('State', default='', choices=c.REGION_OPTS_US)
    region_canada = SelectField('Province', default='', choices=c.REGION_OPTS_CANADA)
    region = StringField('State/Province', default='')
    zip_code = StringField('Zip/Postal Code', default='')
    country = SelectField('Country', default='', validators=[
        validators.InputRequired(message="Please enter a country.")
        ], choices=c.COUNTRY_OPTS, widget=CountrySelect())

    def validate_region(form, field):
        if form.country.data not in ['United States', 'Canada'] and not field.data:
            raise ValidationError('Please enter a state, province, or region.')
    
    def validate_zip_code(form, field):
        if (form.country.data == 'United States' or (not c.COLLECT_FULL_ADDRESS and 
                                                     hasattr(form, 'international') and 
                                                     not form.international.data)) \
            and not c.AT_OR_POST_CON and invalid_zip_code(field.data):
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
