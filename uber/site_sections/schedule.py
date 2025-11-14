import json
import ics
import pytz
import cherrypy

from collections import defaultdict
from datetime import datetime, time, timedelta
from dateutil import parser as dateparser
from time import mktime
from pockets import listify
from pockets.autolog import log
from sqlalchemy.orm import joinedload

from uber.config import c
from uber.decorators import ajax, ajax_gettable, all_renderable, cached, csrf_protected, csv_file, render, schedule_view, site_mappable
from uber.errors import HTTPRedirect
from uber.forms import load_forms
from uber.models import AssignedPanelist, Attendee, Event, EventLocation, PanelApplication
from uber.utils import check, localized_now, normalize_newlines, validate_model, load_locations_from_config


@all_renderable()
class Root:
    @schedule_view
    @csv_file
    def time_ordered(self, out, session):
        for event in session.query(Event).order_by('start_time', 'duration', 'location').all():
            out.writerow([event.timespan(), event.name, event.guidebook_desc, event.location_name])

    @site_mappable(download=True)
    @schedule_view
    def xml(self, session):
        cherrypy.response.headers['Content-type'] = 'text/xml'
        schedule = defaultdict(list)
        for event in session.query(Event).order_by('start_time').all():
            schedule[event.location_name].append(event)
        ordered_event_locations = session.query(EventLocation).order_by(EventLocation.name).all()
        return render('schedule/schedule.xml', {
            'schedule': sorted(schedule.items(), key=lambda tup: c.ORDERED_EVENT_LOCS.index(tup[1][0].location))
        })

    @site_mappable(download=True)
    def ical(self, session, **params):
        icalendar = ics.Calendar()

        if 'locations' not in params or not params['locations']:
            locations = [id for id, name in c.SCHEDULE_LOCATION_OPTS]
            calname = "full"
        else:
            locations = json.loads(params['locations'])
            if len(locations) > 3:
                calname = "partial"
            else:
                calname = "_".join([name for id, name in c.SCHEDULE_LOCATION_OPTS
                                    if str(id) in locations])

        calname = '{}_{}_schedule'.format(c.EVENT_NAME, calname).lower().replace(' ', '_')

        for location in locations:
            for event in session.query(Event)\
                    .filter_by(location=int(location))\
                    .order_by('start_time').all():
                icalendar.events.add(ics.Event(
                    name=event.name,
                    begin=event.start_time,
                    end=(event.start_time + timedelta(minutes=event.duration)),
                    description=normalize_newlines(event.public_description or event.description),
                    created=event.created_info.when,
                    location=event.location_name))

        cherrypy.response.headers['Content-Type'] = \
            'text/calendar; charset=utf-8'
        cherrypy.response.headers['Content-Disposition'] = \
            'attachment; filename="{}.ics"'.format(calname)

        return icalendar

    if not c.HIDE_SCHEDULE:
        ical.restricted = False

    @csv_file
    def panels(self, out, session):
        out.writerow(['Panel', 'Time', 'Duration', 'Room', 'Description', 'Panelists'])
        for event in sorted(session.query(Event).all(), key=lambda e: [e.start_time, e.location_name]):
            if 'Panel' in event.location_name or 'Autograph' in event.location_name:
                panelist_names = ' / '.join(ap.attendee.full_name for ap in sorted(
                    event.assigned_panelists, key=lambda ap: ap.attendee.full_name))

                out.writerow([
                    event.name,
                    event.start_time_local.strftime('%I%p %a').lstrip('0'),
                    '{} minutes'.format(event.duration),
                    event.location_name,
                    event.public_description or event.description,
                    panelist_names])

    @schedule_view
    def panels_json(self, session):
        cherrypy.response.headers['Content-Type'] = 'application/json'
        return json.dumps([
            {
                'name': event.name,
                'location': event.location_name,
                'start': event.start_time_local.strftime('%I%p %a').lstrip('0'),
                'end': event.end_time_local.strftime('%I%p %a').lstrip('0'),
                'start_unix': int(mktime(event.start_time.utctimetuple())),
                'end_unix': int(mktime(event.end_time.utctimetuple())),
                'duration': event.duration,
                'description': event.public_description or event.description,
                'panelists': [panelist.attendee.full_name for panelist in event.assigned_panelists]
            }
            for event in sorted(session.query(Event).all(), key=lambda e: [e.start_time, e.location_name])
        ], indent=4).encode('utf-8')

    @schedule_view
    def now(self, session, when=None):
        if when:
            now = c.EVENT_TIMEZONE.localize(datetime(*map(int, when.split(','))))
        else:
            now = c.EVENT_TIMEZONE.localize(datetime.combine(localized_now().date(), time(localized_now().hour)))

        current, upcoming = [], []
        for loc, desc in c.SCHEDULE_LOCATION_OPTS:
            approx = session.query(Event).filter(Event.location == loc,
                                                 Event.start_time >= now - timedelta(hours=6),
                                                 Event.start_time <= now).all()
            for event in approx:
                if now in event.minutes:
                    current.append(event)

            next_events = session.query(Event).filter(
                Event.location == loc,
                Event.start_time >= now + timedelta(minutes=30),
                Event.start_time <= now + timedelta(hours=4)).order_by('start_time').all()

            if next_events:
                upcoming.extend(event for event in next_events if event.start_time == next_events[0].start_time)

        return {
            'now': now if when else localized_now(),
            'current': current,
            'upcoming': upcoming
        }
    
    def location(self, session, message='', **params):
        if params.get('id') in [None, '', 'None']:
            location = EventLocation()
        else:
            location = session.event_location(params.get('id'))

        forms = load_forms(params, location, ['EventLocationInfo'])

        if cherrypy.request.method == 'POST':
            for form in forms.values():
                form.populate_obj(location)
                session.add(location)
            raise HTTPRedirect('edit?message={}',
                               f"{location.name} location added." if location.is_new else f"{location.name} location updated.")

        return {
            'location': location,
            'message': message,
            'forms': forms,
        }
    
    @ajax
    def validate_location(self, session, form_list=[], **params):
        if params.get('id') in [None, '', 'None']:
            location = EventLocation()
        else:
            location = session.event_location(params.get('id'))

        if not form_list:
            form_list = ['EventLocationInfo']
        elif isinstance(form_list, str):
            form_list = [form_list]

        forms = load_forms(params, location, form_list)
        all_errors = validate_model(forms, location, is_admin=True)

        if all_errors:
            return {"error": all_errors}

        return {"success": True}
    
    @csrf_protected
    def delete_location(self, session, id):
        location = session.event_location(id)

        session.delete(location)
        raise HTTPRedirect('edit?message={}',
                           "Event location deleted.")
    
    @csrf_protected
    def delete_location_cascade(self, session, id):
        location = session.event_location(id)

        event_count = len(location.events)
        for event in location.events:
            session.delete(event)

        session.delete(location)
        raise HTTPRedirect('edit?message={}',
                           f"Event location and {event_count} event(s) deleted.")

    def form(self, session, message='', panelists=(), **params):
        if params.get('id') in [None, '', 'None']:
            event = Event()
        else:
            event = session.event(params.get('id'))

        if 'location_id' in params and cherrypy.request.method != 'POST':
            location = session.event_location(params['location_id'])
            if location.department_id:
                params['department_id'] = location.department_id
            if location.category:
                params['category'] = location.category
            if location.tracks_ints:
                params['tracks'] = location.tracks_ints
            params['event_location_id'] = location.id

        forms = load_forms(params, event, ['EventInfo'])

        assigned_panelists = sorted(event.assigned_panelists, reverse=True, key=lambda a: a.attendee.first_name)

        approved_panel_apps = session.query(PanelApplication).filter(
            PanelApplication.status == c.ACCEPTED,
            PanelApplication.event_id == None).order_by('applied')  # noqa: E711

        if cherrypy.request.method == 'POST':
            for form in forms.values():
                form.populate_obj(event)
            session.add(event)

            # Associate a panel app with this event, and if the event is new, use the panel app's name and title
            if 'panel_id' in params and params['panel_id']:
                add_panel = session.panel_application(id=params['panel_id'])
                add_panel.event_id = event.id
                session.add(add_panel)
                if event.is_new:
                    event.name = add_panel.name
                    event.description = add_panel.description
                    event.public_description = add_panel.public_description
                    for pa in add_panel.applicants:
                        if pa.attendee_id:
                            assigned_panelist = AssignedPanelist(attendee_id=pa.attendee.id, event_id=event.id)
                            session.add(assigned_panelist)

            new_panelist_ids = set(listify(panelists))
            old_panelist_ids = {ap.attendee_id for ap in event.assigned_panelists}
            for ap in event.assigned_panelists:
                if ap.attendee_id not in new_panelist_ids:
                    session.delete(ap)
            for attendee_id in new_panelist_ids:
                if attendee_id not in old_panelist_ids:
                    attendee = session.attendee(id=attendee_id)
                    session.add(AssignedPanelist(event=event, attendee=attendee))
            raise HTTPRedirect('edit?view_event={}&message={}', event.id,
                               f"{event.name} added." if event.is_new else f"{event.name} updated.")

        return {
            'message': message,
            'event':   event,
            'forms': forms,
            'assigned': [ap.attendee_id for ap in assigned_panelists],
            'panelists': [(a.id, a.full_name) for a in session.all_panelists()],
            'approved_panel_apps': approved_panel_apps
        }
    
    @ajax
    def validate_event(self, session, form_list=[], **params):
        if params.get('id') in [None, '', 'None']:
            event = Event()
        else:
            event = session.event(params.get('id'))

        if not form_list:
            form_list = ['EventInfo']
        elif isinstance(form_list, str):
            form_list = [form_list]

        forms = load_forms(params, event, form_list)
        all_errors = validate_model(forms, event, is_admin=True)

        if all_errors:
            return {"error": all_errors}

        return {"success": True}

    @csrf_protected
    def delete(self, session, id):
        event = session.event(id)
        date = event.start_time
        session.delete(session.event(id))
        raise HTTPRedirect('edit?message={}&view_date={}', 'Event successfully deleted', date)

    def edit(self, session, message='', view_date=c.PANELS_EPOCH.date(), view_event=''):
        panelists = defaultdict(dict)
        assigned_panelists = session.query(AssignedPanelist).options(
            joinedload(AssignedPanelist.event), joinedload(AssignedPanelist.attendee)).all()

        for ap in assigned_panelists:
            panelists[ap.event.id][ap.attendee.id] = ap.attendee.full_name

        if view_event:
            event = session.event(view_event)
            view_date = event.start_time_local.date()

        event_list = []
        for event in session.query(Event).order_by('start_time').all():
            event_list.append({
                'id': event.id,
                'resourceIds': [f"{event.location.id}" if event.location else "None"],
                'start': event.start_time_local.strftime('%Y-%m-%d %H:%M:%S'),
                'end': event.end_time_local.strftime('%Y-%m-%d %H:%M:%S'),
                'title': event.name,
                'backgroundColor': "#198754" if event.id == view_event else "#0d6efd",
                'extendedProps': {
                    'desc': event.description,
                    }
            })

        locations = []

        event_locations = session.query(EventLocation)

        if not event_locations.first():
            load_locations_from_config(session)

        location_filters = set()

        for location in event_locations:
            departments = set()

            departments.add(f"{location.department_id}")

            for event in location.events:
                departments.add(f"{event.department_id}")

            locations.append({
                'id': location.id,
                'title': location.schedule_name,
                'extendedProps': {
                    'departments': list(departments),
                }
            })
            if location.department:
                location_filters.add((location.department_id, location.department.name))
        
        if session.query(Event).filter(Event.event_location_id == None).first():
            locations.append({
                'id': "None",
                'title': "No Location",
                'extendedProps': {
                    'departments': ["None"],
                }
            })

        return {
            'events': event_list,
            'locations': locations,
            'filters': location_filters,
            'current_date': f"{view_date}T00:00:00",
            'current_event': view_event,
            'message': message
        }
    
    @ajax
    def update_event(self, session, id, start_time, delta_seconds, location_id):
        event = session.event(id)
        if not event:
            return {'success': False, 'message': "Event not found. Try refreshing the page."}
        event.start_time = c.EVENT_TIMEZONE.localize(dateparser.parse(start_time)).astimezone(pytz.UTC)
        event.duration = event.duration + (int(delta_seconds) / 60)
        event.event_location_id = location_id
        session.commit()
        return {'success': True, 'message': f"{event.name} has been updated!"}

    def panelists_owed_refunds(self, session):
        return {
            'panelists': [a for a in session.query(Attendee)
                                            .filter_by(ribbon=c.PANELIST_RIBBON)
                                            .options(joinedload(Attendee.group))
                                            .order_by(Attendee.full_name).all()
                          if a.paid_for_badge and not a.has_been_refunded]
        }
    
    @csv_file
    def event_panel_info(self, out, session):
        content_opts_enabled = len(c.PANEL_CONTENT_OPTS) > 1
        rating_opts_enabled = len(c.PANEL_RATING_OPTS) > 1
        dept_opts_enabled = len(c.PANELS_DEPT_OPTS) > 1

        out.writerow([
            'Start Time',
            'Panel Name',
            'Department',
            'Panel Type',
            'Description',
            'Schedule Description',
            'Content' if content_opts_enabled else 'Rating',
            'Expected Length',
            'Noise Level',
            'Livestreaming OK',
            'Recording OK',
        ])

        for app in session.query(PanelApplication).join(PanelApplication.event).order_by(Event.start_time):
            app_presentation = app.other_presentation if app.presentation == c.OTHER else app.presentation_label
            app_length = app.length_text if app.length == c.OTHER else app.length_label
            app_record_label = app.livestream_label if len(c.LIVESTREAM_OPTS) > 2 else app.record_label

            if not content_opts_enabled and not rating_opts_enabled:
                content_or_rating = "N/A"
            elif content_opts_enabled:
                content_or_rating = " / ".join(app.granular_rating_labels)
            else:
                content_or_rating = app.rating_label

            out.writerow([app.event.start_time_local, app.name, app.department_label if dept_opts_enabled else 'N/A',
                          app_presentation, app.description, app.public_description, content_or_rating, app_length,
                          app.noise_level_label, app.livestream_label, app_record_label])

    @schedule_view
    @csv_file
    def panel_tech_needs(self, out, session):
        panels = defaultdict(dict)
        panel_applications = session.query(PanelApplication).filter(
            PanelApplication.event_id == Event.id, Event.location.in_(c.PANEL_ROOMS))

        for panel in panel_applications:
            panels[panel.event.start_time_local][panel.event.event_location_id] = panel

        if not panels:
            raise HTTPRedirect('../accounts/homepage?message={}', "No panels have been scheduled yet!")

        curr_time, last_time = min(panels).astimezone(c.EVENT_TIMEZONE), max(panels).astimezone(c.EVENT_TIMEZONE)
        out.writerow(['Panel Starts'] + [c.SCHEDULE_LOCATIONS[room] for room in c.PANEL_ROOMS])
        while curr_time <= last_time:
            row = [curr_time.strftime('%H:%M %a')]
            for room in c.PANEL_ROOMS:
                p = panels[curr_time].get(room)
                row.append('' if not p else '{}\n{}\n{}\n{}'.format(
                    p.event.name,
                    ' / '.join(p.tech_needs_labels),
                    p.other_tech_needs,
                    'Panelists are bringing themselves: {}'.format(p.panelist_bringing) if p.panelist_bringing else ''
                ).strip())
            out.writerow(row)
            curr_time += timedelta(minutes=30)
