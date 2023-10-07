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


def get_override_attr(form, field_name, suffix, *args):
    return getattr(form, field_name + suffix, lambda *args: '')(*args)


def load_forms(params, model, module, form_list, prefix_dict={}, get_optional=True, truncate_prefix='admin', checkboxes_present=True):
    """
    Utility function for initializing several Form objects, since most form pages use multiple Form classes.

    Also adds aliases for common fields, e.g., mapping the `region` column to `region_us` and `region_canada`.
    Aliases are currently only designed to work with text fields and select fields with a [(val, label)] list of choices.

    After loading a form, each field's built-in validators are altered -- this allows us to alter what validations get
    rendered on the page. We use get_optional_fields to mark fields as optional as dictated by their model, and
    we look for a field_name_validators function to replace existing validators via event plugins.

    `params` should be a dictionary from a form submission, usually passed straight from the page handler.
    `model` is the object itself, e.g., the attendee we're loading the form for.
    `form_list` is a list of strings of which form classes to load, e.g., ['PersonalInfo', 'BadgeExtras', 'OtherInfo']
    `prefix_dict` is an optional dictionary to load some of the forms with a prefix. This is useful for loading forms with
        conflicting field names on the same page, e.g., passing {'GroupInfo': 'group_'} will add group_ to all GroupInfo fields.
    `get_optional` is a flag that controls whether or not the forms' get_optional_fields() function is called. Set this to false
        when loading forms for validation, as the validate_model function in utils.py handles optional fields.
    `truncate_prefix` allows you to remove a single word from the form, so e.g. a truncate_prefix of "admin" will save
        "AdminTableInfo" as "table_info." This allows loading admin and prereg versions of forms while using the 
        same form template.

    Returns a dictionary of form objects with the snake-case version of the form as the ID, e.g.,
    the PersonalInfo class will be returned as form_dict['personal_info'].
    """

    form_dict = {}
    alias_dict = {}

    for cls in form_list:
        form_cls = getattr(module, cls, None)
        if not form_cls:
            log.error("We tried to load a form called {} from module {}, but it doesn't seem to exist!".format(cls, str(module)))
            continue

        for model_field_name, aliases in form_cls.field_aliases.items():
            alias_val = params.get(model_field_name, getattr(model, model_field_name))
            for aliased_field in aliases:
                aliased_field_args = getattr(form_cls, aliased_field).kwargs
                choices = aliased_field_args.get('choices')
                if choices:
                    alias_dict[aliased_field] = alias_val if alias_val in [val for val, label in choices] else aliased_field_args.get('default')
                else:
                    alias_dict[aliased_field] = alias_val

        loaded_form = form_cls(params, model, checkboxes_present=checkboxes_present, prefix=prefix_dict.get(cls, ''), data=alias_dict)
        optional_fields = loaded_form.get_optional_fields(model) if get_optional else []

        for name, field in loaded_form._fields.items():
            if name in optional_fields:
                field.validators = [validators.Optional()]
            else:
                override_validators = get_override_attr(loaded_form, name, '_validators', field)
                if override_validators:
                    field.validators = override_validators

        form_label = re.sub(r'(?<!^)(?=[A-Z])', '_', cls).lower()
        if truncate_prefix and form_label.startswith(truncate_prefix + '_'):
            form_label = form_label[(len(truncate_prefix) + 1):]

        form_dict[form_label] = loaded_form

    return form_dict


class MagForm(Form):
    field_aliases = {}

    def get_optional_fields(self, model, is_admin=False):
        return []

    def get_non_admin_locked_fields(self, model):
        return []

    @classmethod
    def all_forms(cls):
        # Get a list of all forms that inherit from this form
        for subclass in cls.__subclasses__():
            module_name = subclass.__module__
            yield from subclass.all_forms()
            yield (module_name, subclass)

    @classmethod
    def form_mixin(cls, form):
        if form.__name__ == 'FormMixin':
            target = getattr(cls, form.__name__)
        elif form.__name__ == cls.__name__:
            target = cls
        else:
            # Search through all form classes, only continue if there is ONE matching form
            match_count = 0
            modules = []
            for module_name, target in cls.all_forms():
                if target.__name__ == form.__name__:
                    if module_name not in modules:
                        match_count += 1
                        real_target = target
                        modules.append(module_name)
            if match_count == 0:
                raise ValueError('Could not find a form with the name {}'.format(form.__name__))
            elif match_count > 1:
                raise ValueError('There is more than one form with the name {}. Please specify which model this form is for.'.format(form.__name__))
            target = real_target

        for name in dir(form):
            if not name.startswith('_'):
                if name in ['get_optional_fields', 'get_non_admin_locked_fields']:
                    setattr(target, "super_" + name, getattr(target, name))
                setattr(target, name, getattr(form, name))
        return target

    def __init__(self, formdata=None, obj=None, prefix='', data=None, meta=None, checkboxes_present=True, **kwargs):
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
                if cherrypy.request.method == 'POST' and checkboxes_present:
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
    
    def populate_obj(self, obj, is_admin=False):
        """
        Adds alias processing, field locking, and data coercion to populate_obj.
        Note that we bypass fields' populate_obj except when filling in aliased fields.
        """
        locked_fields = [] if is_admin else self.get_non_admin_locked_fields(obj)
        for name, field in self._fields.items():
            obj_data = getattr(obj, name, None)
            if name in locked_fields and obj_data and field.data != obj_data:
                log.warning("Someone tried to edit their {} value, but it was locked. \
                            This is either a programming error or a malicious actor.".format(name))
                continue

            column = obj.__table__.columns.get(name)
            if column is not None:
                setattr(obj, name, obj.coerce_column_data(column, field.data))
            else:
                try:
                    setattr(obj, name, field.data)
                except AttributeError:
                    pass # Probably just a collision between a property name and a form field name, e.g., 'badges' for GroupInfo

        for model_field_name, aliases in self.field_aliases.items():
            if model_field_name in locked_fields:
                continue

            for aliased_field in reversed(aliases):
                field_obj = getattr(self, aliased_field, None)
                if field_obj and field_obj.data:
                    field_obj.populate_obj(obj, model_field_name)


    class Meta:
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

            TODO: Changes to field attributes are permanent, so this code only needs to run once per field
            """
            field_name = options.get('name', '')
            if hasattr(form, field_name + '_label'):
                field_label = get_override_attr(form, field_name, '_label')
                if 'label' in unbound_field.kwargs:
                    unbound_field.kwargs['label'] = field_label
                elif unbound_field.args and isinstance(unbound_field.args[0], str):
                    args_list = list(unbound_field.args)
                    args_list[0] = field_label
                    unbound_field.args = tuple(args_list)

            if hasattr(form, field_name + '_desc'):
                unbound_field.kwargs['description'] = get_override_attr(form, field_name, '_desc')
            
            unbound_field.kwargs['render_kw'] = self.set_keyword_defaults(unbound_field, unbound_field.kwargs.get('render_kw', {}), field_name)

            return unbound_field.bind(form=form, **options)

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
        validators.DataRequired("Please enter a street address.")
        ])
    address2 = StringField('Address Line 2', default='')
    city = StringField('City', default='', validators=[
        validators.DataRequired("Please enter a city.")
        ])
    region_us = SelectField('State', default='', validators=[
        validators.DataRequired("Please select a state.")
        ], choices=c.REGION_OPTS_US)
    region_canada = SelectField('Province', default='', validators=[
        validators.DataRequired("Please select a province.")
        ], choices=c.REGION_OPTS_CANADA)
    region = StringField('State/Province', default='', validators=[
        validators.DataRequired("Please enter a state, province, or region.")
        ])
    zip_code = StringField('Zip/Postal Code', default='', validators=[
        validators.DataRequired("Please enter a zip code." if c.COLLECT_FULL_ADDRESS else 
                                 "Please enter a valid 5 or 9-digit zip code.")
        ])
    country = SelectField('Country', default='', validators=[
        validators.DataRequired("Please enter a country.")
        ], choices=c.COUNTRY_OPTS, widget=CountrySelect())

    def get_optional_fields(self, model, is_admin=False):
        optional_list = super().get_optional_fields(model, is_admin)

        if not c.COLLECT_FULL_ADDRESS:
            optional_list.extend(['address1', 'city', 'region', 'region_us', 'region_canada', 'country'])
            if model.international or c.AT_OR_POST_CON:
                optional_list.append('zip_code')
        else:
            if model.country == 'United States':
                optional_list.extend(['region', 'region_canada'])
            elif model.country == 'Canada':
                optional_list.extend(['region', 'region_us'])
            else:
                optional_list.extend(['region_us', 'region_canada'])

        return optional_list
    
    def validate_zip_code(form, field):
        if field.data and (form.country.data == 'United States' or (not c.COLLECT_FULL_ADDRESS and field.flags.required)) \
            and invalid_zip_code(field.data):
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
