import inspect
import re
import six
import cherrypy

from collections import defaultdict, OrderedDict
from wtforms import Form, StringField, SelectField, SelectMultipleField, FileField, IntegerField, BooleanField, validators, Label
import wtforms.widgets.core as wtforms_widgets
from wtforms.validators import ValidationError
from pockets.autolog import log
from functools import wraps

from uber.config import c
from uber.forms.widgets import CountrySelect, IntSelect, MultiCheckbox, NumberInputGroup, SwitchInput, Ranking
from uber.model_checks import invalid_zip_code


def get_override_attr(form, field_name, suffix, *args):
    return getattr(form, field_name + suffix, lambda *args: '')(*args)


def load_forms(params, model, form_list, prefix_dict={}, get_optional=True,
               truncate_prefix='admin', checkboxes_present=True):
    """
    Utility function for initializing several Form objects, since most form pages use multiple Form classes.

    Also adds aliases for common fields, e.g., mapping the `region` column to `region_us` and `region_canada`.
    Aliases are currently only designed to work with text fields and select fields.

    After loading a form, each field's built-in validators are altered -- this allows us to alter what validations get
    rendered on the page. We use get_optional_fields to mark fields as optional as dictated by their model, and
    we look for a field_name_validators function to replace existing validators via event plugins.

    `params` should be a dictionary from a form submission, usually passed straight from the page handler.
    `model` is the object itself, e.g., the attendee we're loading the form for.
    `form_list` is a list of strings of which form classes to load, e.g., ['PersonalInfo', 'BadgeExtras', 'OtherInfo']
    `prefix_dict` is an optional dictionary to load some of the forms with a prefix. This is useful for loading forms
        with conflicting field names on the same page, e.g., passing {'GroupInfo': 'group_'} will add group_ to all
        GroupInfo fields.
    `get_optional` is a flag that controls whether or not the forms' get_optional_fields() function is called.
        Set this to false when loading forms for validation, as the validate_model function in utils.py handles
        optional fields.
    `truncate_prefix` allows you to remove a single word from the form, so e.g. a truncate_prefix of "admin" will save
        "AdminTableInfo" as "table_info." This allows loading admin and prereg versions of forms while using the
        same form template.

    Returns a dictionary of form objects with the snake-case version of the form as the ID, e.g.,
    the PersonalInfo class will be returned as form_dict['personal_info'].
    """

    if not MagForm.initialized:
        MagForm.set_overrides_and_validations()
        MagForm.initialized = True

    form_dict = {}
    alias_dict = {}

    for form_name in form_list:
        try:
            form_cls = MagForm.find_form_class(form_name)
        except ValueError as e:
            log.error(str(e))
            continue

        # Configure and populate fields in "aliased_fields", which store different display logics for a single column
        for model_field_name, aliases in form_cls.field_aliases.items():
            alias_val = params.get(model_field_name, getattr(model, model_field_name))
            for aliased_field in aliases:
                aliased_field_args = getattr(form_cls, aliased_field).kwargs
                choices = aliased_field_args.get('choices')
                if choices:
                    alias_dict[aliased_field] = alias_val if alias_val in [val for val, label in choices
                                                                           ] else aliased_field_args.get('default')
                else:
                    alias_dict[aliased_field] = alias_val

        loaded_form = form_cls(params, model, prefix=prefix_dict.get(form_name, ''))

        for name, field in loaded_form._fields.items():
            # Refresh any choices for fields in "dynamic_choices_fields"
            if name in loaded_form.dynamic_choices_fields.keys():
                field.choices = loaded_form.dynamic_choices_fields[name]()

        loaded_form.process(params, model, checkboxes_present=checkboxes_present, data=alias_dict)

        form_label = re.sub(r'(?<!^)(?=[A-Z])', '_', form_name).lower()
        if truncate_prefix and form_label.startswith(truncate_prefix + '_'):
            form_label = form_label[(len(truncate_prefix) + 1):]

        form_dict[form_label] = loaded_form

    return form_dict


class CustomValidation:
    def __init__(self):
        self.validations = defaultdict(OrderedDict)
        self.required_fields = {}
        self.form = inspect.currentframe().f_back.f_locals.get('cls', None)
        self.field_flags = defaultdict(dict)

    def __bool__(self):
        return bool(self.validations)

    def __getattr__(self, field_name):
        if field_name == '_formfield':
            # Stop WTForms from trying to process these objects as fields
            raise AttributeError("No, we don't have that.")

        def wrapper(func):
            self.validations[field_name][func.__name__] = func
            return func
        return wrapper
    
    def __call__(self, field_name):
        def wrapper(func):
            self.validations[field_name][func.__name__] = func
            return func
        return wrapper
    
    def build_flags_dict(self):
        for field_name, validators in self.get_validation_dict().items():
            for v in validators:
                self.field_flags[field_name].update(getattr(v, 'field_flags', {}))

    def create_required_if(self, message, other_field, condition_lambda=None):
        """
        Factory function to quickly create simple conditional 'required' validations, e.g.,
        requiring a field to be filled out if a checkbox is checked.

        message (str): The error message to display if the validation fails.
        other_field (str): The name of the field that this condition checks. This field
                           MUST be part of the same form.
        condition_lambda (fn): A lambda to evaluate the data from other_field. If not
                               set, other_field is checked for truthiness.
        """
        def validation_func(form, field):
            other_field_data = getattr(form, other_field).data
            if not condition_lambda:
                if other_field_data and not field.data:
                    raise ValidationError(message)
            else:
                if condition_lambda(other_field_data) and not field.data:
                    raise ValidationError(message)
                
        return validation_func

    def set_required_validations(self):
        for field_name, message_or_tuple in self.required_fields.items():
            if not isinstance(message_or_tuple, str):
                try:
                    message, other_field, condition = message_or_tuple
                except ValueError:
                    message, other_field = message_or_tuple
                    condition = None
                self.validations[field_name][f'required_if_{other_field}'] = self.create_required_if(message,
                                                                                                     other_field,
                                                                                                     condition)
            else:
                if self.form and isinstance(getattr(self.form, field_name).field_class, BooleanField):
                    self.validations[field_name]['required'] = validators.InputRequired(message_or_tuple)
                else:
                    self.validations[field_name]['required'] = validators.DataRequired(message_or_tuple)

    def get_validations_by_field(self, field_name):
        field_validations = self.validations.get(field_name)
        return list(field_validations.values()) if field_validations else []

    def get_validation_dict(self):
        all_validations = {}
        for key, dict in self.validations.items():
            all_validations[key] = list(dict.values())
        return all_validations


class MagForm(Form):
    initialized = False

    def __init_subclass__(cls, *args, **kwargs):
        cls.field_aliases = {}
        cls.dynamic_choices_fields = {}
        cls.field_validation, cls.new_or_changed = CustomValidation(), CustomValidation()
        cls.kwarg_overrides = {}
        cls.is_admin = False

    @classmethod
    def set_overrides_and_validations(cls):
        form_list = set([form for module, form in MagForm.all_forms()])
        for form in form_list:
            form.field_validation.set_required_validations()
            form.field_validation.build_flags_dict()
            form.new_or_changed.set_required_validations()
            for ufield in form.__dict__.values():
                if hasattr(ufield, '_formfield'):
                    MagForm.set_keyword_defaults(ufield)

    @classmethod
    def set_keyword_defaults(cls, ufield):
        # Changes the render_kw dictionary for a field to implement some high-level defaults

        render_kw = ufield.kwargs.get('render_kw', {})

        widget = ufield.kwargs.get('widget', None) or ufield.field_class.widget
        if isinstance(widget, wtforms_widgets.TextArea) and 'rows' not in render_kw:
            render_kw['rows'] = 3

        bootstrap_class = ''
        if isinstance(widget, (SwitchInput, wtforms_widgets.CheckboxInput)):
            bootstrap_class = 'form-check-input'
        elif isinstance(widget, wtforms_widgets.Select):
            bootstrap_class = 'form-select'
        elif not isinstance(widget, (MultiCheckbox, IntSelect, Ranking, wtforms_widgets.FileInput,
                                        wtforms_widgets.HiddenInput)):
            bootstrap_class = 'form-control'

        if 'class' in render_kw and bootstrap_class:
            render_kw['class'] += f' {bootstrap_class}'
        elif bootstrap_class:
            render_kw['class'] = bootstrap_class

        ufield.kwargs['render_kw'] = render_kw

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
    def find_form_class(cls, form_name):
        # Search through all form classes, only continue if there is ONE matching form
        match_count = 0
        modules = []
        for module_name, target in cls.all_forms():
            if target.__name__ == form_name:
                if module_name not in modules:
                    match_count += 1
                    real_target = target
                    modules.append(module_name)
        if match_count == 0:
            raise ValueError('Could not find a form with the name {}'.format(form_name))
        elif match_count > 1:
            raise ValueError(f'There is more than one form with the name {form_name}. '
                             'Please specify which model this form is for.')
        return real_target

    @classmethod
    def form_mixin(cls, form):
        if form.__name__ == 'FormMixin':
            target = getattr(cls, form.__name__)
        elif form.__name__ == cls.__name__:
            target = cls
        else:
            target = cls.find_form_class(form.__name__)

        for name in dir(form):
            if not name.startswith('_'):
                if name in ['get_optional_fields', 'get_non_admin_locked_fields']:
                    setattr(target, "super_" + name, getattr(target, name))
                setattr(target, name, getattr(form, name))
        return target

    def process(self, formdata=None, obj=None, data=None, extra_filters=None, checkboxes_present=True, **kwargs):
        formdata = self.meta.wrap_formdata(self, formdata)

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
            use_blank_formdata = cherrypy.request.method == 'POST' and checkboxes_present
            if isinstance(field, BooleanField):
                if not field_in_formdata and field_in_obj:
                    formdata[name] = False if use_blank_formdata else getattr(obj, name)
                elif field_in_formdata and cherrypy.request.method == 'POST':
                    # We have to pre-process boolean fields because WTForms will print "False"
                    # for a BooleanField's hidden input value and then not process that as falsey
                    formdata[name] = formdata[name].strip().lower() not in ('f', 'false', 'n', 'no', '0') \
                        if isinstance(formdata[name], six.string_types) else formdata[name]
            elif (isinstance(field, SelectMultipleField)
                  or hasattr(obj, 'all_checkgroups') and name in obj.all_checkgroups
                  ) and not field_in_formdata and field_in_obj:
                if use_blank_formdata:
                    formdata[name] = []
                elif field_in_obj and isinstance(getattr(obj, name), str):
                    formdata[name] = getattr(obj, name).split(',')
                else:
                    formdata[name] = getattr(obj, name)

        super().process(formdata, obj, data, extra_filters, **kwargs)

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
                    pass  # Indicates collision between a property name and a field name, like 'badges' for GroupInfo

        for model_field_name, aliases in self.field_aliases.items():
            if model_field_name in locked_fields:
                continue

            for aliased_field in reversed(aliases):
                field_obj = getattr(self, aliased_field, None)
                # I'm pretty sure this prevents an aliased field from zeroing out a value
                # Right now we prefer that but we may want to change it later
                if field_obj and field_obj.data:
                    field_obj.populate_obj(obj, model_field_name)

    class Meta:
        def get_field_type(self, field):
            # Returns a key telling our Jinja2 form input macro how to render the scaffolding based on the widget
            # Deprecated -- remove when the old form_input macro is gone

            widget = field.widget
            if isinstance(widget, SwitchInput):
                return 'switch'
            elif isinstance(widget, wtforms_widgets.CheckboxInput):
                return 'checkbox'
            elif isinstance(widget, NumberInputGroup):
                return 'inputgroup'
            elif isinstance(widget, MultiCheckbox):
                return 'checkgroup'
            elif isinstance(widget, CountrySelect):
                return 'text'
            elif isinstance(widget, wtforms_widgets.Select):
                return 'select'
            elif isinstance(widget, IntSelect):
                return 'customselect'
            elif isinstance(widget, wtforms_widgets.HiddenInput):
                return 'hidden'
            elif isinstance(widget, Ranking):
                return 'ranking'
            elif isinstance(widget, wtforms_widgets.FileInput):
                return 'file'
            else:
                return 'text'

        def bind_field(self, form, unbound_field, options):
            """
            This function implements all our custom logic to apply when initializing a field. Currently, we:
            - Get a label and description override from a function on the form class, if there is one
            - Add aria-describedby to the field for use in clientside validations

            We don't do this in MagForm.initialize because we don't have access to the field name at that point.
            """

            bound_field = unbound_field.bind(form=form, **options)

            field_name = options.get('name', '')

            if hasattr(form, field_name + '_label'):
                field_label = get_override_attr(form, field_name, '_label')
                
                bound_field.label = Label(bound_field.id, field_label)

            if hasattr(form, field_name + '_desc'):
                bound_field.description = get_override_attr(form, field_name, '_desc')
            
            if field_name in form.field_validation.field_flags:
                for flag_name, val in form.field_validation.field_flags[field_name].items():
                    setattr(bound_field.flags, flag_name, True)
                    bound_field.render_kw[flag_name] = val

            return bound_field

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
        from uber.models import Group

        optional_list = super().get_optional_fields(model, is_admin)

        if not c.COLLECT_FULL_ADDRESS and (not isinstance(model, Group) or not model.is_dealer):
            optional_list.extend(['address1', 'city', 'region', 'region_us', 'region_canada', 'country'])
            if getattr(model, 'international', None) or c.AT_OR_POST_CON:
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
        if not c.COLLECT_FULL_ADDRESS:
            if getattr(form, 'international', None):
                skip_validation = form.international.data
            elif getattr(form, 'country', None):
                skip_validation = form.country.data != 'United States'
            else:
                skip_validation = False
        else:
            if getattr(form, 'country', None):
                skip_validation = form.country.data != 'United States'
            else:
                skip_validation = False

        if field.data and invalid_zip_code(field.data) and not skip_validation:
            raise ValidationError('Please enter a valid 5 or 9-digit zip code.')


class HiddenIntField(IntegerField):
    widget = wtforms_widgets.HiddenInput()


class HiddenBoolField(BooleanField):
    widget = wtforms_widgets.HiddenInput()


class SelectAvailableField(SelectField):
    """
    A select field that takes a flat list `sold_out_list` and compares each option to that list.
    If an option is in the list, `sold_out_text` is displayed alongside it.
    To avoid type errors, the values in `sold_out_list` are coerced to the `coerce` value passed on init.
    """

    def __init__(self, label=None, validators=None, coerce=str, choices=None, validate_choice=True,
                 sold_out_list_func=[], sold_out_text="(SOLD OUT!)", **kwargs):
        super().__init__(label, validators, coerce, choices, validate_choice, **kwargs)
        self.sold_out_list_func = sold_out_list_func
        self.sold_out_text = sold_out_text

    def get_sold_out_list(self):
        return [self.coerce(val) for val in self.sold_out_list_func()]

    def _choices_generator(self, choices):
        sold_out_list = self.get_sold_out_list()
        if not choices:
            _choices = []
        elif isinstance(choices[0], (list, tuple)):
            _choices = choices
        else:
            _choices = zip(choices, choices)

        for value, label in _choices:
            coerced_val = self.coerce(value)
            if coerced_val in sold_out_list:
                label = f"{label} {self.sold_out_text}"

            yield (value, label, coerced_val == self.data)


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
from uber.forms.group import *  # noqa: F401,E402,F403
from uber.forms.artist_marketplace import *  # noqa: F401,E402,F403
from uber.forms.panels import *  # noqa: F401,E402,F403
from uber.forms.security import *  # noqa: F401,E402,F403
from uber.forms.hotel_lottery import *  # noqa: F401,E402,F403