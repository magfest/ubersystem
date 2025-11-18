from wtforms import validators
from wtforms.validators import ValidationError

from uber.config import c
from uber.forms.attraction import BaseAttractionInfo, AttractionInfo, AttractionFeatureInfo, AttractionEventInfo
from uber.model_checks import validation
from uber.utils import localized_now


BaseAttractionInfo.field_validation.required_fields = {
    'waitlist_slots': ("Please enter the number of slots for the waitlist, or 0 for an unlimited waitlist.",
                       'waitlist_available', lambda x: not x.data and x.data != 0),
    'signups_open_relative': ("Signups must start at least one minute before an event.",
                              'signups_open_type', lambda x: x.data == 'relative'),
    'signups_open_time': ("Please select a time for signups to open.",
                          'signups_open_type', lambda x: x.data == 'absolute'),
}


AttractionInfo.field_validation.required_fields = {
    'name': "Please enter a name for this attraction.",
    'description': "Please enter a listing description for this attraction.",
    'slots': "Please set the minimum number of slots to at least 1.",
}

AttractionFeatureInfo.field_validation.required_fields = {
    'name': "Please enter a name for this feature.",
    'description': "Please enter a description for this attraction.",
    'slots': "Please set the minimum number of slots to at least 1.",
}


AttractionEventInfo.field_validation.required_fields = {
    'event_location_id': "Please select a location.",
    'start_time': "Please set a start time.",
    'duration': "Events must be at least one minute long.",
    'slots': "Events must have at least one slot.",
}