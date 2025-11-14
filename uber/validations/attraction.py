from wtforms import validators
from wtforms.validators import ValidationError

from uber.config import c
from uber.forms.attraction import AttractionEventInfo
from uber.model_checks import validation
from uber.utils import localized_now




AttractionEventInfo.field_validation.required_fields = {
    'event_location_id': "Please select a location.",
    'start_time': "Please set a start time.",
    'duration': "Events must be at least one minute long.",
    'slots': "Events must have at least one slot.",
    'signups_open_relative': ("Signups must start at least one minute before an event.", 'signups_open_type', lambda x: x.data == 'relative'),
    'signups_open_time': ("Please select a time for signups to open.", 'signups_open_type', lambda x: x.data == 'absolute'),
}
