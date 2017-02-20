from uber.common import *

__version__ = 'v0.1'

attendee_fields = [
    'full_name', 'first_name', 'last_name', 'email', 'zip_code', 'cellphone', 'ec_name', 'ec_phone', 'badge_status_label', 'checked_in',
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

job_fields = dict({
    'name': True,
    'description': True,
    'location': True,
    'start_time': True,
    'end_time': True,
    'duration': True,
    'shifts': {
        'attendee': {
            'badge_num': True,
            'full_name': True,
            'first_name': True,
            'last_name': True,
            'email': True,
            'cellphone': True,
            'badge_printed_name': True
        }
    }

})


class JobLookup:
    def lookup(self, location):
        with Session() as session:
            columns = Job.__table__.columns
            location_column = columns['location']
            label_lookup = {val: key for key, val in location_column.type.choices.items()}
            return [job.to_dict(job_fields) for job in session.query(Job).filter_by(location=label_lookup[location]).all()]

services.register(JobLookup(), 'shifts')


class DepartmentLookup:
    def list(self):
        with Session() as session:
            output = {}
            for dept in c.JOB_LOCATION_VARS:
                output[dept] = dict(c.JOB_LOCATION_OPTS)[getattr(c, dept)]
            return output

services.register(DepartmentLookup(), 'dept')

config_fields = [
    'EVENT_NAME',
    'ORGANIZATION_NAME',
    'YEAR',
    'EPOCH',

    'EVENT_VENUE',
    'EVENT_VENUE_ADDRESS',

    'AT_THE_CON',
    'POST_CON',

]


class ConfigLookup:
    def info(self):
        output = {
            'API_VERSION': __version__
        }
        for field in config_fields:
            output[field] = getattr(c, field)
        return output

    def lookup(self, field):
        if field.upper() in config_fields:
            return getattr(c, field.upper())

services.register(ConfigLookup(), 'config')
