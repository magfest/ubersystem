import cherrypy
from datetime import date

from markupsafe import Markup
from wtforms import (BooleanField, DateField, EmailField,
                     HiddenField, SelectField, SelectMultipleField, IntegerField,
                     StringField, TelField, validators, TextAreaField)
from wtforms.validators import ValidationError, StopValidation

from uber.config import c
from uber.forms import (AddressForm, MultiCheckbox, MagForm, SelectAvailableField, SwitchInput, NumberInputGroup,
                        HiddenBoolField, HiddenIntField, CustomValidation, Ranking)
from uber.custom_tags import popup_link
from uber.badge_funcs import get_real_badge_type
from uber.models import Attendee, BadgeInfo, Session, PromoCodeGroup
from uber.model_checks import invalid_phone_number
from uber.utils import get_age_conf_from_birthday


__all__ = ['DepartmentInfo']


class DepartmentInfo(MagForm):
    admin_desc = True

    name = StringField('Name')
    description = StringField(
        'Description', description="Displayed to potential volunteers during registration.")
    solicits_volunteers = BooleanField("This department publically asks volunteers for help.")
    is_shiftless = BooleanField("This department does not use shift signups.")
    max_consecutive_minutes = IntegerField(
        "Max Consecutive Hours",
        description="The maximum number of consecutive hours a staffer may work. Enter 0 for no limit.")
    from_email = EmailField("Department Email")
    manages_panels = BooleanField("This department accepts panel applications.")
    panels_desc = TextAreaField(
        "Panel Application Description",
        description="What text, if any, should be shown when applying for a panel for this department?")
    parent_id = HiddenField()
    is_setup_approval_exempt = HiddenField()
    is_teardown_approval_exempt = HiddenField()

    def populate_obj(self, obj, is_admin=False):
        max_minutes = self._fields.get('max_consecutive_minutes', None)
        if max_minutes and max_minutes.data:
            max_minutes.data = max_minutes.data * 60
        super().populate_obj(obj, is_admin)
