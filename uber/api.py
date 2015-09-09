from uber.common import *

attendee_fields = [
    'full_name', 'first_name', 'last_name', 'email', 'zip_code', 'cellphone', 'ec_phone', 'badge_status_label', 'checked_in',
    'badge_type_label', 'ribbon_label', 'staffing', 'is_dept_head', 'assigned_depts_labels', 'weighted_hours', 'worked_hours',
    'badge_num'
]
fields = dict({
    'food_restrictions': {
        'sandwich_pref_labels': True,
        'standard_labels': True,
        'freeform': True
    },
    'shifts': {
        'worked_label': True,
        'job': ['type_label', 'location_label', 'name', 'description', 'start_time', 'end_time', 'extra15']
    }
}, **{field: True for field in attendee_fields})


class AttendeeLookup:
    def lookup(self, badge_num):
        with Session() as session:
            attendee = session.query(Attendee).filter_by(badge_num=badge_num).first()
            return attendee.to_dict(fields) if attendee else {'error': 'No attendee found with Badge #{}'.format(badge_num)}

    def search(self, query):
        with Session() as session:
            return [a.to_dict(fields) for a in session.search(query).all()]

services.register(AttendeeLookup(), 'attendee')
