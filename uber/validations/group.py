import re

from datetime import date
from pockets import classproperty
from wtforms import validators
from wtforms.validators import ValidationError, StopValidation

from uber.badge_funcs import get_real_badge_type
from uber.config import c
from uber.custom_tags import format_currency
from uber.models import Attendee, Session
from uber.model_checks import invalid_zip_code, invalid_phone_number
from uber.utils import get_age_from_birthday, get_age_conf_from_birthday
from uber.decorators import form_validation, new_or_changed_validation, post_form_validation

###### Attendee-Facing Validations ######
@form_validation.categories
def dealer_other_category(form, field):
    if field.data and c.OTHER in field.data and not form.categories_text.data:
        return "Please describe what 'other' categories your wares fall under."
    
@post_form_validation.none
def edit_only_correct_statuses(group):
    if group.status not in [c.WAITLISTED, c.CANCELLED, c.DECLINED]:
        return "You cannot change your {} after it has been {}.".format(c.DEALER_APP_TERM, group.status_label)

###### Admin-Only Validations ######
@form_validation.cost
def group_money(form, field):
    if not form.auto_recalc.data:
        try:
            cost = int(float(field.data if field.data else 0))
            if cost < 0:
                return 'Total Group Price must be a number that is 0 or higher.'
        except Exception:
            return "What you entered for Total Group Price ({}) isn't even a number".format(field.data)