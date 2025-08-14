import inspect
import re
import six
import cherrypy

from collections import defaultdict, OrderedDict
from wtforms import Form, StringField, SelectField, SelectMultipleField, IntegerField, BooleanField, validators, Label
import wtforms.widgets.core as wtforms_widgets
from wtforms.validators import ValidationError, StopValidation
from wtforms.utils import unset_value
from pockets.autolog import log
from functools import wraps

from uber.config import c
from uber.forms.widgets import DateMaskInput, IntSelect, MultiCheckbox, SwitchInput, Ranking, UniqueList
from uber.model_checks import invalid_phone_number


def valid_cellphone(form, field):
    if field.data and invalid_phone_number(field.data):
        raise ValidationError('Please provide a valid 10-digit US phone number or '
                              'include a country code (e.g. +44) for international numbers.')


def maximum_values(form, field):
    if not field.data:
        return

    if isinstance(field.data, six.string_types) and len(field.data) > 10000:
        raise ValidationError('Please enter under 10,000 characters.')
    if isinstance(field.data, list) and len(field.data) > 1000:
        raise ValidationError('Please select fewer than 1,000 options.')
    if isinstance(field.data, cherrypy._cpreqbody.Part):
        if field.data.file:
            field.data.file.seek(0)
            file_size = len(field.data.file.read()) / (1024 * 1024)
            field.data.file.seek(0)
            if file_size > 5:
                raise ValidationError("Please upload a file under 5MB.")

    try:
        val = int(field.data)
        if val > 100000000001:
            raise ValidationError('Please enter a number under 100,000,000,000.')
        if val < -100000000001:
            raise ValidationError('Please enter a number above -100,000,000,000.')
    except (ValueError, TypeError):
        pass


def get_override_attr(form, field_name, suffix, *args):
    return getattr(form, field_name + suffix, lambda *args: '')(*args)


def load_forms(params, model, form_list, field_prefix='', truncate_prefix='admin',
               checkboxes_present=True, force_form_defaults=True, read_only=False):
    """
    Utility function for initializing several Form objects, since most form pages use multiple Form classes.

    Also adds aliases for common fields, e.g., mapping the `region` column to `region_us` and `region_canada`.
    Aliases are currently only designed to work with text fields and select fields.

    `params` should be a dictionary from a form submission, usually passed straight from the page handler.
    `model` is the object itself, e.g., the attendee we're loading the form for.
    `form_list` is a list of strings of which form classes to load, e.g., ['PersonalInfo', 'BadgeExtras', 'OtherInfo']
    `field_prefix` is an optional string to use as a prefix. This is useful for loading forms
        with conflicting field names on the same page, e.g., passing 'group_' will add group_ to all the forms loaded
        in this call.
    `truncate_prefix` allows you to remove a single word from the form, so e.g. a truncate_prefix of "admin" will save
        "AdminTableInfo" as "table_info." This allows loading admin and prereg versions of forms while using the
        same form template.
    `checkboxes_present` lets us avoid setting unchecked checkboxes to false if they are not present on the form.
    `force_form_defaults` makes the field default value override the model's value if there are no parameters passed
        and the object has not been saved to the database.
    `read_only` lets you set all fields in the loaded forms to be read-only. Input types that don't use the readonly property,
        such as checkboxes, will be set to disabled instead. To make only some fields in a form read-only, pass `readonly`
        or `disabled` to the form input macro instead.

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

        loaded_form = form_cls(params, model, prefix=field_prefix, checkboxes_present=checkboxes_present,
                               data=alias_dict, force_form_defaults=force_form_defaults, field_prefix=field_prefix)
        loaded_form.read_only = read_only

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

    def create_required_if(self, message, other_field_name, condition_lambda=None):
        """
        Factory function to quickly create simple conditional 'required' validations, e.g.,
        requiring a field to be filled out if a checkbox is checked.

        message (str): The error message to display if the validation fails.
        other_field_name (str): The name of the field that this condition checks. This field
                                MUST be part of the same form.
        condition_lambda (fn): A lambda to evaluate the data from other_field. If not
                               set, other_field is checked for truthiness. If this function
                               calls field properties (e.g. field.name), we pass it the
                               field itself instead of the field's data.
        """
        def validation_func(form, field):
            other_field = getattr(form, other_field_name, None)
            if not condition_lambda:
                if not other_field or other_field.data and not field.data:
                    raise StopValidation(message)
            else:
                try:
                    result = condition_lambda(other_field.data)
                except AttributeError:
                    result = condition_lambda(other_field)

                if result and not field.data:
                    raise StopValidation(message)
                
        return validation_func

    def set_required_validations(self):
        for field_name, message_or_tuple in self.required_fields.items():
            if not isinstance(message_or_tuple, str):
                try:
                    message, other_field, condition = message_or_tuple
                except ValueError:
                    message, other_field = message_or_tuple
                    condition = None
                self.validations[field_name][f'required_if_{other_field}'] = self.create_required_if(
                    message, other_field, condition)
                self.validations[field_name].move_to_end(f'required_if_{other_field}', last=False)
            else:
                if self.form and isinstance(getattr(self.form, field_name).field_class, BooleanField):
                    self.validations[field_name]['required'] = validators.InputRequired(message_or_tuple)
                else:
                    self.validations[field_name]['required'] = validators.DataRequired(message_or_tuple)
                self.validations[field_name].move_to_end('required', last=False)

    def set_email_validators(self, field_name):
        self.validations[field_name]['length'] = validators.Length(
            max=255, message="Email addresses cannot be longer than 255 characters.")
        self.validations[field_name]['valid'] = validators.Email(granular_message=True)

    def set_phone_validators(self, field_name):
        self.validations[field_name]['valid'] = valid_cellphone

    def set_server_max(self, field_name):
        self.validations[field_name]['server_max'] = maximum_values

    def get_validations_by_field(self, field_name):
        field_validations = self.validations.get(field_name)
        return list(field_validations.values()) if field_validations else []

    def get_validation_dict(self):
        all_validations = {}
        for key, validation_dict in self.validations.items():
            if not hasattr(validation_dict, 'values'):
                raise AttributeError(f"Problem with {self.form} '{key}' validations: {validation_dict}"
                                     " is not a dictionary. Did you forget to specify a second key?")
            all_validations[key] = list(validation_dict.values())
        return all_validations


class MagForm(Form):
    initialized = False
    field_aliases = {}
    dynamic_choices_fields = {}
    admin_desc = False

    def __init_subclass__(cls, *args, **kwargs):
        cls.field_validation, cls.new_or_changed = CustomValidation(), CustomValidation()
        cls.has_inherited = False
        cls.is_admin = False
        cls.model = None
        cls.read_only = False

    @classmethod
    def set_overrides_and_validations(cls):
        form_list = set([form for module, form in MagForm.all_forms()])
        
        def build_parents(form):
            # I am not good at generators
            real_list = []
            def generator(form):
                if form != MagForm:
                    real_list.append(form)
                    for next_form in form.__bases__:
                        yield from generator(next_form)
                    yield form
            list(generator(form))
            return real_list

        # Set up validations and field flags in order from parent to child
        for form in form_list:
            ascending_list = build_parents(form)
            for descending_form in reversed(ascending_list):
                if hasattr(descending_form, 'has_inherited') and not descending_form.has_inherited:
                    for inherit_from in [f for f in descending_form.__bases__ if
                                         hasattr(f, 'field_validation')]:
                        MagForm.inherit_validations(descending_form, inherit_from)
                    descending_form.field_validation.set_required_validations()
                    descending_form.field_validation.build_flags_dict()
                    descending_form.new_or_changed.set_required_validations()
                    descending_form.has_inherited = True

        # These apply equally to all fields, so they shouldn't be inherited
        for form in form_list:
            for field_name, ufield in form.__dict__.items():
                if hasattr(ufield, '_formfield'):
                    MagForm.set_keyword_defaults(ufield)
                    if ufield.field_class.__name__ == "EmailField":
                        form.field_validation.set_email_validators(field_name)
                    elif ufield.field_class.__name__ == "TelField":
                        form.field_validation.set_phone_validators(field_name)
                    elif 'length' not in form.field_validation.validations[field_name]:
                        form.field_validation.set_server_max(field_name)

    @classmethod
    def inherit_validations(cls, form, inherit_from):
        for field_name in inherit_from.field_validation.validations.keys():
            if hasattr(form, field_name):
                form.field_validation.validations[field_name].update(
                    inherit_from.field_validation.validations[field_name])
        for field_name in inherit_from.field_validation.field_flags.keys():
            if hasattr(form, field_name):
                form.field_validation.field_flags[field_name].update(
                    inherit_from.field_validation.field_flags[field_name])
        for field_name in inherit_from.new_or_changed.validations.keys():
            if hasattr(form, field_name):
                form.new_or_changed.validations[field_name].update(
                    inherit_from.field_validation.validations[field_name])

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
                if name in ['get_non_admin_locked_fields']:
                    setattr(target, "super_" + name, getattr(target, name))
                setattr(target, name, getattr(form, name))
        return target

    def process(self, formdata={}, obj=None, data=None, extra_filters=None,
                checkboxes_present=True, force_form_defaults=True, **kwargs):
        formdata = self.meta.wrap_formdata(self, formdata)

        # Special form data preprocessing!
        #
        # Checkboxes aren't submitted in HTML forms if they're unchecked; additionally, there is a bug in WTForms
        # So if a checkbox isn't present in the params, we use the object's value UNLESS this form was submitted,
        # in which case we set it to false
        #
        # We also convert our MultiChoice value (a string) into the list of strings that WTForms expects
        # and convert DOBs into the format that our DateMaskInput expects
        # and process our UniqueList field data if it's been submitted as multiple fields

        force_defaults = force_form_defaults and (not obj or obj.is_new)

        for name, field in self._fields.items():
            if kwargs.get('field_prefix', ''):
                prefixed_name = f"{kwargs['field_prefix']}-{name}"
            else:
                prefixed_name = name

            field_in_obj = hasattr(obj, name)
            field_in_formdata = prefixed_name in formdata
            use_blank_formdata = cherrypy.request.method == 'POST' and checkboxes_present and formdata
            if isinstance(field, BooleanField):
                if not field_in_formdata and field_in_obj:
                    formdata[prefixed_name] = False if use_blank_formdata else getattr(obj, name)
                elif field_in_formdata and cherrypy.request.method == 'POST':
                    # We have to pre-process boolean fields because WTForms will print "False"
                    # for a BooleanField's hidden input value and then not process that as falsey
                    formdata[prefixed_name] = formdata[prefixed_name].strip().lower() not in ('f', 'false', 'n', 'no', '0') \
                        if isinstance(formdata[prefixed_name], six.string_types) else formdata[prefixed_name]
            elif (isinstance(field, SelectMultipleField)
                  or hasattr(obj, 'all_checkgroups') and name in obj.all_checkgroups
                  or isinstance(field.widget, SelectButtonGroup)
                  ) and not field_in_formdata and field_in_obj:
                if use_blank_formdata:
                    formdata[prefixed_name] = []
                elif field_in_obj and isinstance(getattr(obj, name), str):
                    formdata[prefixed_name] = getattr(obj, name).split(',')
                else:
                    formdata[prefixed_name] = getattr(obj, name)
            elif isinstance(field.widget, DateMaskInput) and not field_in_formdata and getattr(obj, name, None):
                formdata[prefixed_name] = getattr(obj, name).strftime('%m/%d/%Y')
            elif isinstance(field.widget, UniqueList) and field_in_formdata and isinstance(formdata[prefixed_name], list):
                formdata[prefixed_name] = ','.join(formdata[prefixed_name])

            if force_defaults and not field_in_formdata and not isinstance(field, BooleanField):
                if field.default is not None:
                    formdata[prefixed_name] = field.default
                elif hasattr(obj, name):
                    formdata[prefixed_name] = getattr(obj, name)
                elif name in kwargs:
                    formdata[prefixed_name] = kwargs[name]
                else:
                    formdata[prefixed_name] = unset_value

        super().process(formdata, None if force_defaults else obj, data, extra_filters, **kwargs)

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
        def bind_field(self, form, unbound_field, options):
            """
            This function implements all our custom logic to apply when initializing a field. Currently, we:
            - Add a reference to the field so we can traverse back up to its form
            - Refresh the field's choices if it's listed in the form's `dynamic_choices_fields`
            - Get a label and description override from a function on the form class, if there is one
            - Add aria-describedby to the field for use in clientside validations

            We don't do this in MagForm.initialize because we don't have access to the field name at that point.
            """

            bound_field = unbound_field.bind(form=form, **options)
            bound_field.form = form
            bound_field.render_kw = unbound_field.kwargs.get('render_kw', {})  # TODO: Remove after conversion?

            field_name = options.get('name', '')

            if field_name in form.dynamic_choices_fields.keys():
                bound_field.choices = form.dynamic_choices_fields[field_name]()

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


class AddressForm(MagForm):
    field_aliases = {'region': ['region_us', 'region_canada']}

    address1 = StringField('Address Line 1', default='')
    address2 = StringField('Address Line 2', default='')
    city = StringField('City', default='')
    region_us = StringField('State')
    region_canada = StringField('Province')
    region = StringField('State/Province', default='')
    zip_code = StringField('Zip/Postal Code', default='')
    country = StringField('Country')


class HiddenIntField(IntegerField):
    widget = wtforms_widgets.HiddenInput()


class HiddenBoolField(BooleanField):
    widget = wtforms_widgets.HiddenInput()


class BlankOrIntegerField(IntegerField):
    widget = wtforms_widgets.TextInput()
    def process_data(self, value):
        if value is None or value is unset_value or value == '':
            self.data = None
            return

        try:
            self.data = int(value)
        except (ValueError, TypeError) as exc:
            self.data = None
            raise ValueError(self.gettext("Not a valid integer value.")) from exc

    def process_formdata(self, valuelist):
        if not valuelist or valuelist[0] == '':
            return

        try:
            self.data = int(valuelist[0])
        except ValueError as exc:
            self.data = None
            raise ValueError(self.gettext("Not a valid integer value.")) from exc


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

        for value, label, *other_args in _choices:
            coerced_val = self.coerce(value)
            if coerced_val in sold_out_list:
                label = f"{label} {self.sold_out_text}"
            selected = coerced_val == self.data
            render_kw = other_args[0] if len(other_args) else {}
            yield (value, label, selected, render_kw)


class DictWrapper(dict):
    def getlist(self, arg):
        if arg in self:
            if isinstance(self[arg], list):
                return self[arg]
            else:
                return [self[arg]]
        else:
            return []


from uber.forms.widgets import *  # noqa: F401,E402,F403
from uber.forms.art_show import *  # noqa: F401,E402,F403
from uber.forms.attendee import *  # noqa: F401,E402,F403
from uber.forms.department import *  # noqa: F401,E402,F403
from uber.forms.group import *  # noqa: F401,E402,F403
from uber.forms.artist_marketplace import *  # noqa: F401,E402,F403
from uber.forms.panels import *  # noqa: F401,E402,F403
from uber.forms.security import *  # noqa: F401,E402,F403
from uber.forms.showcase import *  # noqa: F401,E402,F403
from uber.forms.hotel_lottery import *  # noqa: F401,E402,F403