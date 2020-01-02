import uuid
from datetime import datetime, timedelta

import cherrypy
import pytz
from pockets import listify, sluggify
from sqlalchemy.orm import subqueryload

from uber.config import c
from uber.decorators import ajax, all_renderable, csrf_protected, csv_file
from uber.errors import HTTPRedirect
from uber.models import AdminAccount, Attendee, Attraction, AttractionFeature, AttractionEvent, AttractionSignup, \
    utcmin
from uber.site_sections.attractions import _attendee_for_badge_num
from uber.utils import check, filename_safe


@all_renderable()
class Root:
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

        if cherrypy.request.method == 'POST':
            if 'advance_notices' in params:
                ns = listify(params.get('advance_notices', []))
                params['advance_notices'] = [int(n) for n in ns if n != '']

            attraction = session.attraction(
                params,
                bools=Attraction.all_bools,
                checkgroups=Attraction.all_checkgroups)
            message = check(attraction)
            if not message:
                if not attraction.department_id:
                    attraction.department_id = None
                session.add(attraction)
                raise HTTPRedirect(
                    'form?id={}&message={}',
                    attraction.id,
                    '{} updated successfully'.format(attraction.name))
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
            'attraction': attraction
        }

    def new(self, session, message='', **params):
        if params.get('id', 'None') != 'None':
            raise HTTPRedirect('form?id={}', params['id'])

        if 'advance_notices' in params:
            ns = listify(params.get('advance_notices', []))
            params['advance_notices'] = [int(n) for n in ns if n != '']

        admin_account = session.current_admin_account()
        attraction = session.attraction(
            params,
            bools=Attraction.all_bools,
            checkgroups=Attraction.all_checkgroups)
        if not attraction.department_id:
            attraction.department_id = None

        if cherrypy.request.method == 'POST':
            message = check(attraction)
            if not message:
                attraction.owner = admin_account
                session.add(attraction)
                raise HTTPRedirect('form?id={}', attraction.id)

        return {
            'admin_account': admin_account,
            'attraction': attraction,
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

        if not attraction_id \
                and (not params.get('id') or params.get('id') == 'None'):
            raise HTTPRedirect('index')

        feature = session.attraction_feature(
            params,
            bools=AttractionFeature.all_bools,
            checkgroups=AttractionFeature.all_checkgroups)

        attraction_id = feature.attraction_id or attraction_id
        attraction = session.query(Attraction).filter_by(id=attraction_id) \
            .order_by(Attraction.id).one()

        if cherrypy.request.method == 'POST':
            if feature.is_new:
                feature.attraction_id = attraction_id
            message = check(feature)

            if not message:
                session.add(feature)

                raise HTTPRedirect(
                    'form?id={}&message={}',
                    attraction_id,
                    'The {} feature was successfully {}'.format(
                        feature.name, 'created' if feature.is_new else 'updated'))
            session.rollback()

        return {
            'attraction': attraction,
            'feature': feature,
            'message': message
        }

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

    def event(
            self,
            session,
            attraction_id=None,
            feature_id=None,
            previous_id=None,
            delay=0,
            message='',
            **params):

        if not attraction_id or attraction_id == 'None':
            attraction_id = None
        if not feature_id or feature_id == 'None':
            feature_id = None
        if not previous_id or previous_id == 'None':
            previous_id = None

        if not attraction_id and not feature_id and not previous_id \
                and (not params.get('id') or params.get('id') == 'None'):
            raise HTTPRedirect('index')

        event = session.attraction_event(
            params,
            bools=AttractionEvent.all_bools,
            checkgroups=AttractionEvent.all_checkgroups)

        if not event.is_new:
            attraction_id = event.feature.attraction_id

        previous = None
        feature = None
        if feature_id:
            feature = session.query(AttractionFeature).get(feature_id)
            attraction_id = feature.attraction_id

        try:
            delay = int(delay)
        except ValueError:
            delay = 0

        if cherrypy.request.method == 'POST':
            event.attraction_id = attraction_id
            message = check(event)
            if not message:
                is_new = event.is_new
                session.add(event)
                session.flush()
                session.refresh(event)
                message = 'The event for {} was successfully {}'.format(
                    event.label, 'created' if is_new else 'updated')

                for param in params.keys():
                    if param.startswith('save_another_'):
                        delay = param[13:]
                        raise HTTPRedirect(
                            'event?previous_id={}&delay={}&message={}',
                            event.id, delay, message)
                raise HTTPRedirect(
                    'form?id={}&message={}', attraction_id, message)
            session.rollback()
        elif previous_id:
            previous = session.query(AttractionEvent).get(previous_id)
            attraction_id = previous.feature.attraction_id
            event.feature = previous.feature
            event.attraction_feature_id = previous.attraction_feature_id
            event.attraction_id = attraction_id
            event.location = previous.location
            event.start_time = previous.end_time + timedelta(seconds=delay)
            event.duration = previous.duration
            event.slots = previous.slots
        elif event.is_new and feature and feature.events:
            events_by_location = feature.events_by_location
            location = next(reversed(events_by_location))
            recent = events_by_location[location][-1]
            event.attraction_id = recent.attraction_id
            event.location = recent.location
            event.start_time = recent.end_time + timedelta(seconds=delay)
            event.duration = recent.duration
            event.slots = recent.slots

        attraction = session.query(Attraction).get(attraction_id)

        return {
            'attraction': attraction,
            'feature': feature or event.feature,
            'event': event,
            'message': message
        }

    @csrf_protected
    def edit_event_gap(self, session, id=None, gap=0):
        if not id or id == 'None':
            raise HTTPRedirect('index')

        try:
            gap = int(gap)
        except Exception:
            gap = None

        if gap is not None and cherrypy.request.method == 'POST':
            ref_event = session.query(AttractionEvent).get(id)
            events_for_day = ref_event.feature.events_by_location_by_day[ref_event.location][ref_event.start_day_local]
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
                    if event.location == int(old_location):
                        event.location = int(new_location)
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
                'is_checked_in': True,
                'event': {
                    'location': True,
                    'location_label': True,
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
    def checkin_signup(self, session, id):
        message = ''
        if cherrypy.request.method == 'POST':
            signup = session.query(AttractionSignup).get(id)
            if signup.is_checked_in:
                message = "You cannot check in a signup that has already checked in"
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
