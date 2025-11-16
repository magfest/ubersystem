import uuid
from datetime import datetime, timedelta

import cherrypy
import pytz
from pockets import listify, sluggify
from sqlalchemy.orm import subqueryload

from uber.config import c
from uber.decorators import ajax, all_renderable, csrf_protected, csv_file, not_site_mappable, site_mappable
from uber.errors import HTTPRedirect
from uber.forms import load_forms
from uber.models import AdminAccount, Attendee, Attraction, AttractionFeature, AttractionEvent, AttractionSignup, \
    utcmin
from uber.site_sections.attractions import _attendee_for_badge_num
from uber.tasks.attractions import send_waitlist_notification
from uber.utils import check, filename_safe, validate_model


@all_renderable()
class Root:
    @site_mappable
    def index(self, session, filtered=False, message='', **params):
        admin_account = session.current_admin_account()
        if filtered:
            attraction_filter = [Attraction.owner_id == admin_account.id]
        else:
            attraction_filter = []

        attractions = session.query(Attraction).filter(*attraction_filter) \
            .options(
                subqueryload(Attraction.department),
                subqueryload(Attraction.owner)
                .subqueryload(AdminAccount.attendee)) \
            .order_by(Attraction.name).all()

        return {
            'admin_account': admin_account,
            'filtered': filtered,
            'message': message,
            'attractions': attractions
        }

    def form(self, session, message='', **params):
        attraction_id = params.get('id')
        if not attraction_id or attraction_id == 'None':
            raise HTTPRedirect('index')
        
        attraction = session.attraction(attraction_id)
        
        forms = load_forms(params, attraction, ['AttractionInfo'])

        if cherrypy.request.method == 'POST':
            for form in forms.values():
                form.populate_obj(attraction)

            if 'signups_open_type' in params:
                attraction.update_signup_times(params['signups_open_type'])

            attraction.update_dept_ids(session)
            attraction.cascade_feature_event_attrs(session)
            
            raise HTTPRedirect(
                'form?id={}&message={}',
                attraction.id,
                '{} updated successfully.'.format(attraction.name))
        else:
            attraction = session.query(Attraction) \
                .filter_by(id=attraction_id) \
                .options(
                    subqueryload(Attraction.department),
                    subqueryload(Attraction.features)
                    .subqueryload(AttractionFeature.events)
                    .subqueryload(AttractionEvent.attendees)) \
                .order_by(Attraction.id).one()

        return {
            'admin_account': session.current_admin_account(),
            'message': message,
            'attraction': attraction,
            'forms': forms,
        }
    
    @ajax
    def validate_attraction(self, session, form_list=[], **params):
        if params.get('id') in [None, '', 'None']:
            attraction = Attraction()
        else:
            attraction = session.attraction(params.get('id'))

        if not form_list:
            form_list = ['AttractionInfo']
        elif isinstance(form_list, str):
            form_list = [form_list]

        forms = load_forms(params, attraction, form_list)
        all_errors = validate_model(forms, attraction, is_admin=True)

        if all_errors:
            return {"error": all_errors}

        return {"success": True}

    @ajax
    def open_signups(self, session, **params):
        feature = session.attraction_feature(params.get('feature_id'))
        if not feature:
            return {'error': 'Feature not found!'}

        for event in feature.events_by_location_by_day[params.get('location')][params.get('day')]:
            event.signups_open_relative = 0
            event.signups_open_time = datetime.now(pytz.UTC)
            session.add(event)

        session.commit()
        return {'success': True}

    @ajax
    def close_signups(self, session, **params):
        feature = session.attraction_feature(params.get('feature_id'))
        if not feature:
            return {'error': 'Feature not found!'}

        for event in feature.events_by_location_by_day[params.get('location')][params.get('day')]:
            event.signups_open_time = None
            session.add(event)

        session.commit()
        return {'success': True}

    def new(self, session, message='', **params):
        if params.get('id', 'None') != 'None':
            raise HTTPRedirect('form?id={}', params['id'])

        admin_account = session.current_admin_account()
        attraction = Attraction()
        session.add(attraction)

        forms = load_forms(params, attraction, ['AttractionInfo'])

        if cherrypy.request.method == 'POST':
            for form in forms.values():
                form.populate_obj(attraction)

            if 'signups_open_type' in params:
                attraction.update_signup_times(params['signups_open_type'])

            attraction.owner = admin_account

            raise HTTPRedirect('form?id={}', attraction.id)

        return {
            'admin_account': admin_account,
            'attraction': attraction,
            'forms': forms,
            'message': message,
        }

    @csrf_protected
    def delete(self, session, id, message=''):
        if cherrypy.request.method == 'POST':
            attraction = session.query(Attraction).get(id)
            attendee = session.admin_attendee()
            if not attendee.can_admin_attraction(attraction):
                raise HTTPRedirect(
                    'form?id={}&message={}',
                    id,
                    "You cannot delete an attraction that you don't own")

            session.delete(attraction)
            raise HTTPRedirect(
                'index?message={}',
                'The {} attraction was deleted'.format(attraction.name))

        raise HTTPRedirect('form?id={}', id)

    def feature(self, session, attraction_id=None, message='', **params):
        if not attraction_id or attraction_id == 'None':
            attraction_id = None

        if not params.get('id') or params.get('id') == 'None':
            if attraction_id:
                feature = AttractionFeature()
            else:
                raise HTTPRedirect('index')
        else:
            feature = session.attraction_feature(params.get('id'))

        attraction_id = feature.attraction_id or attraction_id
        attraction = session.query(Attraction).filter_by(id=attraction_id) \
            .order_by(Attraction.id).one()
        
        feature.attraction = attraction
        if feature.is_new:
            params = dict(feature.default_params, **params)
        
        forms = load_forms(params, feature, ['AttractionFeatureInfo'])

        if cherrypy.request.method == 'POST':
            for form in forms.values():
                form.populate_obj(feature)

            if 'signups_open_type' in params:
                feature.update_signup_times(params['signups_open_type'])

            feature.update_name_desc(session)
            feature.cascade_event_attrs(session)
            session.add(feature)

            raise HTTPRedirect(
                'form?id={}&message={}',
                attraction_id,
                'The {} feature was successfully {}.'.format(
                    feature.name, 'created' if feature.is_new else 'updated'))

        return {
            'attraction': attraction,
            'feature': feature,
            'forms': forms,
            'message': message
        }
    
    @ajax
    def validate_feature(self, session, form_list=[], **params):
        if params.get('id') in [None, '', 'None']:
            feature = AttractionFeature()
        else:
            feature = session.attraction_feature(params.get('id'))

        if not form_list:
            form_list = ['AttractionFeatureInfo']
        elif isinstance(form_list, str):
            form_list = [form_list]

        forms = load_forms(params, feature, form_list)
        all_errors = validate_model(forms, feature, is_admin=True)

        if all_errors:
            return {"error": all_errors}

        return {"success": True}

    @csrf_protected
    def delete_feature(self, session, id):
        feature = session.query(AttractionFeature).get(id)
        attraction_id = feature.attraction_id
        message = ''
        if cherrypy.request.method == 'POST':
            attraction = session.query(Attraction).get(attraction_id)
            if not session.admin_attendee().can_admin_attraction(attraction):
                message = "You cannot delete a feature from an attraction you don't own"
            else:
                session.delete(feature)
                raise HTTPRedirect(
                    'form?id={}&message={}',
                    attraction_id,
                    'The {} feature was deleted'.format(feature.name))

        if not message:
            raise HTTPRedirect('form?id={}', attraction_id)
        else:
            raise HTTPRedirect('form?id={}&message={}', attraction_id, message)

    @csv_file
    def export_feature(self, out, session, id):
        from uber.decorators import _set_response_filename
        feature = session.query(AttractionFeature).get(id)
        _set_response_filename('{}.csv'.format(filename_safe(feature.name)))
        out.writerow(['Name', 'Badge Name', 'Badge Num', 'Signup Time', 'Checkin Time'])
        for event in feature.events:
            for signup in event.signups:
                out.writerow([
                    signup.attendee.full_name,
                    signup.attendee.badge_printed_name,
                    signup.attendee.badge_num,
                    signup.signup_time_label,
                    signup.checkin_time_label
                ])

    def event(self, session, previous_id=None, delay=0, message='', **params):
        if params.get('feature_id', 'None') == 'None':
            params['feature_id'] = None
        if not previous_id or previous_id == 'None':
            previous_id = None

        feature = None

        try:
            delay = int(delay)
        except ValueError:
            delay = 0

        if not params['feature_id'] and not previous_id and params.get('id') in [None, '', 'None']:
            raise HTTPRedirect('index?message={}', "Could not set up an event as we don't know what feature it should be in.")

        if params.get('id') in [None, '', 'None']:
            event = AttractionEvent()
        else:
            event = session.attraction_event(params.get('id'))
            feature = event.feature

        if not feature and (params['feature_id'] or params.get('attraction_feature_id', '')):
            feature = session.query(AttractionFeature).get(params.get('attraction_feature_id', params['feature_id']))

        if cherrypy.request.method != 'POST':
            last_event = None

            if previous_id:
                last_event = session.attraction_event(previous_id)
            elif event.is_new and feature and feature.events:
                events_by_location = feature.events_by_location
                location = next(reversed(events_by_location))
                last_event = events_by_location[location][-1]

            if last_event:
                feature = last_event.feature
                params.update({
                    'attraction_feature_id': last_event.attraction_feature_id,
                    'event_location_id': last_event.event_location_id,
                    'start_time': last_event.end_time + timedelta(minutes=delay),
                    'duration': last_event.duration,
                })
            
            event.feature = feature
            params = dict(event.default_params, **params)

        params['attraction_id'] = feature.attraction_id
        params['attraction_feature_id'] = feature.id

        forms = load_forms(params, event, ['AttractionEventInfo'])

        if cherrypy.request.method == 'POST':
            is_new = event.is_new
            for form in forms.values():
                form.populate_obj(event)
            
            if 'signups_open_type' in params:
                event.update_signup_times(params['signups_open_type'])

            session.add(event)
            session.flush()
            session.refresh(event)
            message = 'The event for {} was successfully {}.'.format(event.label, 'created' if is_new else 'updated')
            
            event.sync_with_schedule(session)

            for param in params.keys():
                if param.startswith('save_another_'):
                    delay = param[13:]
                    raise HTTPRedirect(
                        'event?previous_id={}&delay={}&message={}',
                        event.id, delay, message)
            raise HTTPRedirect(
                'form?id={}&message={}', feature.attraction_id, message)

        return {
            'attraction': feature.attraction,
            'feature': feature,
            'event': event,
            'forms': forms,
            'message': message,
        }

    @ajax
    def validate_event(self, session, form_list=[], **params):
        if params.get('id') in [None, '', 'None']:
            event = AttractionEvent()
        else:
            event = session.attraction_event(params.get('id'))

        if not form_list:
            form_list = ['AttractionEventInfo']
        elif isinstance(form_list, str):
            form_list = [form_list]

        forms = load_forms(params, event, form_list)
        all_errors = validate_model(forms, event, is_admin=True)

        if all_errors:
            return {"error": all_errors}

        return {"success": True}
    
    @csv_file
    def signups_export(self, out, session, id):
        event = session.attraction_event(id)
        out.writerow(['Attendee', 'Badge #', 'Cellphone', 'Email', 'Signup Time', 'Checked In'])
        for signup in event.signups:
            out.writerow([signup.attendee.full_name, signup.attendee.badge_num, signup.attendee.cellphone,
                          signup.attendee.email, signup.signup_time_local, signup.checkin_time_local or 'N/A'])

    @csrf_protected
    @not_site_mappable
    def edit_event_gap(self, session, id=None, gap=0):
        if not id or id == 'None':
            raise HTTPRedirect('index')

        try:
            gap = int(gap)
        except Exception:
            gap = None

        if gap is not None and cherrypy.request.method == 'POST':
            ref_event = session.query(AttractionEvent).get(id)
            events_for_day = ref_event.feature.events_by_location_by_day[ref_event.event_location_id][ref_event.start_day_local]
            attraction_id = ref_event.feature.attraction_id

            delta = None
            prev_event = None
            for event in events_for_day:
                if prev_event == ref_event:
                    prev_gap = (event.start_time - prev_event.end_time).total_seconds()
                    delta = timedelta(seconds=(gap - prev_gap))
                if delta is not None:
                    event.start_time += delta
                prev_event = event
            raise HTTPRedirect(
                'form?id={}&message={}', attraction_id, 'Events updated')
        raise HTTPRedirect('form?id={}', attraction_id)

    @ajax
    def update_locations(self, session, feature_id, old_location, new_location):
        message = ''
        if cherrypy.request.method == 'POST':
            feature = session.query(AttractionFeature).get(feature_id)
            if not session.admin_attendee().can_admin_attraction(feature.attraction):
                message = "You cannot update rooms for an attraction you don't own"
            else:
                for event in feature.events:
                    if event.event_location_id == old_location:
                        event.event_location_id = new_location
                session.commit()
        if message:
            return {'error': message}

    @ajax
    def delete_event(self, session, id):
        message = ''
        if cherrypy.request.method == 'POST':
            event = session.query(AttractionEvent).get(id)
            attraction_id = event.feature.attraction_id
            attraction = session.query(Attraction).get(attraction_id)
            if not session.admin_attendee().can_admin_attraction(attraction):
                message = "You cannot delete a event from an attraction you don't own"
            else:
                session.delete(event)
                session.commit()
        if message:
            return {'error': message}

    @ajax
    def cancel_signup(self, session, id):
        message = ''
        if cherrypy.request.method == 'POST':
            signup = session.query(AttractionSignup).get(id)
            attraction_id = signup.event.feature.attraction_id
            attraction = session.query(Attraction).get(attraction_id)
            if not session.admin_attendee().can_admin_attraction(attraction):
                message = "You cannot cancel a signup for an attraction you don't own"
            elif signup.is_checked_in:
                message = "You cannot cancel a signup that has already checked in"
            else:
                if not signup.on_waitlist:
                    signup.event.add_next_waitlist(session)
                session.delete(signup)
                session.commit()
        if message:
            return {'error': message}

    def checkin(self, session, message='', **params):
        id = params.get('id')
        if not id:
            raise HTTPRedirect('index')

        try:
            uuid.UUID(id)
            filters = [Attraction.id == id]
        except Exception:
            filters = [Attraction.slug.startswith(sluggify(id))]

        attraction = session.query(Attraction).filter(*filters).first()
        if not attraction:
            raise HTTPRedirect('index')

        return {'attraction': attraction, 'message': message}

    @ajax
    def get_signups(self, session, badge_num, attraction_id=None):
        from uber.barcode import get_badge_num_from_barcode

        if cherrypy.request.method == 'POST':
            try:
                badge_num = int(badge_num)
            except ValueError:
                badge_num = get_badge_num_from_barcode(badge_num)['badge_num']

            attendee = _attendee_for_badge_num(
                session, badge_num,
                subqueryload(Attendee.attraction_signups)
                .subqueryload(AttractionSignup.event)
                .subqueryload(AttractionEvent.feature))

            if not attendee:
                return {'error': 'Unrecognized badge number: {}'.format(badge_num)}

            signups = attendee.attraction_signups
            if attraction_id:
                signups = [s for s in signups if s.event.feature.attraction_id == attraction_id]

            read_spec = {
                'signup_time': True,
                'checkin_time': True,
                'on_waitlist': True,
                'waitlist_position': True,
                'is_checked_in': True,
                'event': {
                    'event_location_id': True,
                    'location_room_name': True,
                    'start_time': True,
                    'start_time_label': True,
                    'duration': True,
                    'time_span_label': True,
                    'slots': True,
                    'feature': True}}

            signups = sorted(signups, key=lambda s: s.event.start_time)
            return {
                'result': {
                    'signups': [s.to_dict(read_spec) for s in signups],
                    'attendee': attendee.to_dict()
                }
            }

    @ajax
    def pull_from_waitlist(self, session, id, email=False):
        message = ''
        email = True if email == 'true' else False
        if cherrypy.request.method == 'POST':
            signup = session.query(AttractionSignup).get(id)
            if signup.is_checked_in:
                message = "This attendee has already checked in."
            else:
                signup.on_waitlist = False
                if email:
                    send_waitlist_notification.delay(signup.id)
                session.commit()
                return {'result': ''}
        if message:
            return {'error': message}

    @ajax
    def checkin_signup(self, session, id):
        message = ''
        if cherrypy.request.method == 'POST':
            signup = session.query(AttractionSignup).get(id)
            if signup.is_checked_in:
                message = "This attendee has already checked in."
            elif signup.on_waitlist:
                message = "This attendee is still on the waitlist for this event."
            else:
                signup.checkin_time = datetime.now(pytz.UTC)
                session.commit()
                return {'result': signup.checkin_time.astimezone(c.EVENT_TIMEZONE)}
        if message:
            return {'error': message}

    @ajax
    def undo_checkin_signup(self, session, id):
        if cherrypy.request.method == 'POST':
            signup = session.query(AttractionSignup).get(id)
            signup.checkin_time = utcmin.datetime
            session.commit()
