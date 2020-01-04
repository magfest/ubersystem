import uuid
from datetime import datetime

import cherrypy
from pytz import UTC
from pockets import sluggify
from sqlalchemy.orm import subqueryload

from uber.config import c
from uber.decorators import ajax, all_renderable
from uber.errors import HTTPRedirect
from uber.models.attraction import Attendee, Attraction, AttractionFeature, AttractionEvent, AttractionSignup
from uber.site_sections.preregistration import check_post_con


def _attendee_for_badge_num(session, badge_num, options=None):
    from uber.barcode import get_badge_num_from_barcode
    
    if not badge_num:
        return None

    try:
        badge_num = int(badge_num)
    except ValueError:
        badge_num = get_badge_num_from_barcode(badge_num)['badge_num']
    except Exception:
        return None

    query = session.query(Attendee).filter_by(badge_num=badge_num)
    if options:
        query = query.options(options)
    return query.first()


def _attendee_for_info(session, first_name, last_name, email, zip_code):
    if not (first_name and last_name and email and zip_code):
        return None

    try:
        return session.lookup_attendee(first_name, last_name, email, zip_code)
    except Exception:
        return None


def _model_for_id(session, model, id, options=None, filters=[]):
    if not id:
        return None

    try:
        uuid.UUID(id)
    except Exception:
        return None

    query = session.query(model).filter(model.id == id, *filters)
    if options:
        query = query.options(options)
    return query.first()


@all_renderable(public=True)
@check_post_con
class Root:
    @cherrypy.expose
    def default(self, *args, **kwargs):
        if args:
            if kwargs.get('feature', None):
                return self.events(
                    slug=sluggify(args[0]),
                    feature=sluggify(kwargs['feature']))
            else:
                return self.features(slug=sluggify(args[0]))
        else:
            raise HTTPRedirect('index')

    def index(self, session, **params):
        attractions = session.query(Attraction).filter_by(is_public=True) \
            .options(subqueryload(Attraction.public_features)) \
            .order_by(Attraction.name).all()
        return {'attractions': attractions}

    def features(self, session, id=None, slug=None, **params):
        filters = [Attraction.is_public == True]  # noqa: E712
        options = subqueryload(Attraction.public_features) \
            .subqueryload(AttractionFeature.events).subqueryload(AttractionEvent.attendees)

        if slug:
            attraction = session.query(Attraction) \
                .filter(Attraction.slug.startswith(slug), *filters) \
                .options(options).first()
        else:
            attraction = _model_for_id(
                session, Attraction, id, options, filters)

        if not attraction:
            raise HTTPRedirect('index')

        no_events = datetime.max.replace(tzinfo=UTC)  # features with no events should sort to the end
        features = attraction.public_features
        return {
            'attraction': attraction,
            'features': sorted(features, key=lambda f: f.events[0].start_time if f.events else no_events),
            'show_all': params.get('show_all')}

    def events(self, session, id=None, slug=None, feature=None, **params):
        filters = [AttractionFeature.is_public == True]  # noqa: E712
        options = subqueryload(AttractionFeature.events) \
            .subqueryload(AttractionEvent.attendees)

        if slug and feature:
            attraction = session.query(Attraction).filter(
                Attraction.is_public == True,
                Attraction.slug.startswith(slug)).first()  # noqa: E712
            if attraction:
                feature = session.query(AttractionFeature).filter(
                    AttractionFeature.attraction_id == attraction.id,
                    AttractionFeature.slug.startswith(feature),
                    *filters).options(options).first()
            else:
                feature = None
        else:
            feature = _model_for_id(
                session, AttractionFeature, id, options, filters)

        if not feature:
            if attraction:
                raise HTTPRedirect(attraction.slug)
            else:
                raise HTTPRedirect('index')
        return {'feature': feature}

    def manage(self, session, id=None, **params):
        attendee = _model_for_id(session, Attendee, id, subqueryload(
            Attendee.attraction_signups)
            .subqueryload(AttractionSignup.event)
            .subqueryload(AttractionEvent.feature)
            .subqueryload(AttractionFeature.attraction))

        if not attendee:
            raise HTTPRedirect('index')
        if attendee.amount_unpaid:
            raise HTTPRedirect(
                '../preregistration/attendee_donation_form?id={}', attendee.id)
        return {
            'attractions': session.query(Attraction).order_by('name').all(),
            'attendee': attendee,
            'has_checked_in': any(
                s.is_checked_in for s in attendee.attraction_signups),
            'has_unchecked_in': any(
                s.is_unchecked_in for s in attendee.attraction_signups),
            'signups': sorted(
                attendee.attraction_signups,
                key=lambda s: s.event.checkin_start_time)}

    @ajax
    def verify_badge_num(self, session, badge_num, **params):
        attendee = _attendee_for_badge_num(session, badge_num)
        if not attendee:
            return {'error': 'Unrecognized badge number: {}'.format(badge_num)}

        if attendee.attractions_opt_out:
            return {'error': 'That attendee has disabled attraction signups'}

        return {
            'first_name': attendee.first_name,
            'badge_num': attendee.badge_num}

    @ajax
    def signup_for_event(self, session, id, badge_num='', first_name='',
                         last_name='', email='', zip_code='', **params):

        # Badge number during the event is a hard requirement for Autographs
        if badge_num or c.AFTER_EPOCH:
            attendee = _attendee_for_badge_num(session, badge_num)
            if not attendee:
                return {
                    'error': 'Unrecognized badge number: {}'.format(badge_num)
                }
        else:
            attendee = _attendee_for_info(session, first_name, last_name,
                                          email, zip_code)
            if not attendee:
                return {'error': 'No attendee is registered with that info'}

        if attendee.amount_unpaid:
            return {'error': 'That attendee is not fully paid up'}

        if attendee.attractions_opt_out:
            return {'error': 'That attendee has disabled attraction signups'}

        event = _model_for_id(session, AttractionEvent, id)
        if not event:
            return {'error': 'Unrecognized event id: {}'.format(id)}

        old_remaining_slots = event.remaining_slots

        if event not in attendee.attraction_events:
            attraction = event.feature.attraction
            if attraction.restriction == Attraction._PER_ATTRACTION:
                if attraction in attendee.attractions:
                    return {'error': '{} is already signed up for {}'.format(
                            attendee.first_name, attraction.name)}
            elif attraction.restriction == Attraction._PER_FEATURE:
                if event.feature in attendee.attraction_features:
                    return {'error': '{} is already signed up for {}'.format(
                            attendee.first_name, event.feature.name)}

            if event.is_sold_out:
                return {'error': '{} is already sold out'.format(event.label)}

            event.attendee_signups.append(attendee)
            session.commit()

        return {
            'first_name': attendee.first_name,
            'badge_num': attendee.badge_num,
            'notification_pref': attendee.notification_pref,
            'masked_notification_pref': attendee.masked_notification_pref,
            'event_id': event.id,
            'is_sold_out': event.is_sold_out,
            'remaining_slots': event.remaining_slots,
            'old_remaining_slots': old_remaining_slots}

    @ajax
    def cancel_signup(self, session, attendee_id, id):
        message = ''
        if cherrypy.request.method == 'POST':
            signup = session.query(AttractionSignup).get(id)
            if signup.attendee_id != attendee_id:
                message = "You cannot cancel someone else's signup"
            elif signup.is_checked_in:
                message = "You cannot cancel a signup after you've checked in"
            else:
                session.delete(signup)
                session.commit()
        if message:
            return {'error': message}
        return {}

    @ajax
    def opt_out(self, session, id, attractions_opt_out):
        if cherrypy.request.method == 'POST':
            attendee = session.query(Attendee).get(id)
            opt_out = str(attractions_opt_out).lower()
            attendee.attractions_opt_out = opt_out == 'true'
            session.commit()
        return {}

    @ajax
    def notification_pref(self, session, id, notification_pref):
        if cherrypy.request.method == 'POST':
            attendee = session.query(Attendee).get(id)
            attendee.notification_pref = notification_pref
            session.commit()
        return {}
