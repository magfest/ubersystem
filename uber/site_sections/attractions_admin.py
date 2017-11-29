from uber.common import *


@all_renderable(c.PEOPLE)
class Root:
    def index(self, session, filtered=False, message='', **params):
        if filtered:
            admin_account_id = cherrypy.session['account_id']
            attraction_filter = [Attraction.owner_id == admin_account_id]
        else:
            attraction_filter = []

        attractions = session.query(Attraction).filter(*attraction_filter) \
            .options(
                subqueryload(Attraction.department),
                subqueryload(Attraction.owner)
                    .subqueryload(AdminAccount.attendee)) \
            .order_by(Attraction.name).all()

        return {
            'filtered': filtered,
            'message': message,
            'attractions': attractions
        }

    def form(self, session, message='', **params):
        attraction_id = params.get('id')
        if not attraction_id or attraction_id == 'None':
            raise HTTPRedirect('index')

        if cherrypy.request.method == 'POST':
            if 'notifications' in params:
                ns = listify(params.get('notifications', []))
                params['notifications'] = [int(n) for n in ns if n != '']

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
                .order_by(Attraction.id) \
                .one()

        return {
            'admin_account': session.current_admin_account(),
            'message': message,
            'attraction': attraction
        }

    def new(self, session, message='', **params):
        if params.get('id', 'None') != 'None':
            raise HTTPRedirect('form?id={}', params['id'])

        if 'notifications' in params:
            ns = listify(params.get('notifications', []))
            params['notifications'] = [int(n) for n in ns if n != '']

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
                    "You cannot delete a attraction that you don't own")

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
                message = "You cannot delete a feature from a attraction you don't own"
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

    def event(self, session, attraction_id=None, message='', **params):
        if not attraction_id or attraction_id == 'None':
            attraction_id = None

        previous_id = params.pop('previous_id', None)
        if not attraction_id and not previous_id \
                and (not params.get('id') or params.get('id') == 'None'):
            raise HTTPRedirect('index')

        event = session.attraction_event(
            params,
            bools=AttractionEvent.all_bools,
            checkgroups=AttractionEvent.all_checkgroups)

        attraction_id = (
            event.feature and event.feature.attraction_id) or attraction_id

        if cherrypy.request.method == 'POST':
            message = check(event)
            if not message:
                session.add(event)
                session.flush()
                session.refresh(event)
                message = 'The event for {} was successfully {}'.format(
                    event.label, 'created' if event.is_new else 'updated')

                if 'save_another' in params:
                    raise HTTPRedirect(
                        'event?previous_id={}&message={}', event.id, message)
                else:
                    raise HTTPRedirect(
                        'form?id={}&message={}', attraction_id, message)
            session.rollback()
        elif previous_id:
            previous = session.query(AttractionEvent).get(previous_id)
            attraction_id = previous.feature.attraction_id
            event.attraction_feature_id = previous.attraction_feature_id
            event.location = previous.location
            event.start_time = previous.end_time
            event.duration = previous.duration
            event.slots = previous.slots

        attraction = session.query(Attraction).filter_by(id=attraction_id) \
            .order_by(Attraction.id).one()

        return {
            'attraction': attraction,
            'event': event,
            'message': message
        }

    @ajax
    def update_locations(self, session, id, old_location, new_location):
        message = ''
        if cherrypy.request.method == 'POST':
            attraction = session.query(Attraction).get(id)
            if not session.admin_attendee().can_admin_attraction(attraction):
                message = "You cannot update rooms for an attraction you don't own"
            else:
                for event in attraction.events:
                    if event.location == int(old_location):
                        event.location = int(new_location)
                session.commit()
        if message:
            return {'error': message}

    @ajax
    def delete_event(self, session, id):
        event = session.query(AttractionEvent).get(id)
        attraction_id = event.feature.attraction_id
        message = ''
        if cherrypy.request.method == 'POST':
            attraction = session.query(Attraction).get(attraction_id)
            if not session.admin_attendee().can_admin_attraction(attraction):
                message = "You cannot delete a event from a attraction you don't own"
            else:
                session.delete(event)
                session.commit()
        if message:
            return {'error': message}
