from collections import defaultdict
from datetime import datetime, timedelta

import cherrypy
from pockets import groupify
from pockets.autolog import log
from sqlalchemy.orm import joinedload

from uber.config import c
from uber.decorators import ajax, all_renderable, csrf_protected, csv_file
from uber.errors import HTTPRedirect
from uber.models import AssignedPanelist, Attendee, AutomatedEmail, Event, EventFeedback, \
    PanelApplicant, PanelApplication
from uber.utils import add_opt, check


@all_renderable()
class Root:
    def index(self, session, message=''):
        return {
            'message': message,
            'apps': session.panel_apps()
        }

    def app(self, session, id, message='', csrf_token='', explanation=None):
        return {
            'message': message,
            'app': session.panel_application(id),
            'current_tracks': [track for track in session.query(PanelApplication.track).distinct().all() if track[0]],
        }

    def form(self, session, message='', **params):
        app = session.panel_application(params,
                                        checkgroups=PanelApplication.all_checkgroups,
                                        bools=PanelApplication.all_bools)
        if cherrypy.request.method == 'POST':
            message = check(app)
            if not message:
                raise HTTPRedirect('app?id={}&message={}', app.id, 'Application updated')

        return {
            'app': app,
            'message': message
        }

    def email_statuses(self, session):
        emails = session.query(AutomatedEmail).filter(AutomatedEmail.ident.in_(
            ['panel_accepted', 'panel_declined', 'panel_waitlisted', 'panel_scheduled']))
        return {'emails': groupify(emails, 'ident')}

    def assigned_to(self, session, id):
        attendee = session.attendee(id)
        return {
            'attendee': attendee,
            'panels': sorted(attendee.panel_applications, key=lambda app: app.name)
        }

    @csrf_protected
    def update_comments(self, session, id, comments):
        session.panel_application(id).comments = comments
        raise HTTPRedirect('app?id={}&message={}', id, 'Comments updated')

    @csrf_protected
    def mark(self, session, status, **params):
        app = session.panel_application(params)
        if app.status != c.ACCEPTED and int(status) == c.ACCEPTED:
            app.accepted = datetime.now()
        app.status = int(status)
        if not app.poc:
            app.poc_id = session.admin_attendee().id
        raise HTTPRedirect('index?message={}{}{}', app.name, ' was marked as ', app.status_label)

    @csrf_protected
    def set_poc(self, session, app_id, poc_id):
        app = session.panel_application(app_id)
        app.poc = session.attendee(poc_id)
        raise HTTPRedirect('app?id={}&message={}{}', app.id, 'Point of contact was updated to ', app.poc.full_name)

    @csrf_protected
    def update_track(self, session, id, **params):
        app = session.panel_application(id)
        app.track = params.get('track', '')
        raise HTTPRedirect('app?id={}&message={}', app.id, 'Track updated')

    def edit_panelist(self, session, **params):
        is_post = cherrypy.request.method == 'POST'
        panelist = session.panel_applicant(params, checkgroups=PanelApplicant.all_checkgroups, ignore_csrf=not is_post)
        application = session.query(PanelApplication).get(params.get('app_id', panelist.app_id))
        if is_post:
            message = check(panelist)
            if message:
                return {'message': message, 'panelist': panelist, 'application': application}
            session.add(panelist)
            session.commit()
            raise HTTPRedirect('app?id={}&message={} was successfully updated', application.id, panelist.full_name)
        return {'panelist': PanelApplicant if panelist.is_new else panelist, 'application': application}

    @csrf_protected
    def change_submitter(self, session, applicant_id):
        panelist = session.panel_applicant(applicant_id)
        for each_panelist in panelist.application.applicants:
            each_panelist.submitter = False
        panelist.submitter = True
        raise HTTPRedirect('app?id={}&message=Point of contact was updated to {}', panelist.app_id, panelist.full_name)

    @csrf_protected
    def remove_submitter(self, session, applicant_id):
        panelist = session.panel_applicant(applicant_id)
        session.delete(panelist)
        raise HTTPRedirect('app?id={}&message=Panelist {} was removed', panelist.app_id, panelist.full_name)

    def associate(self, session, message='', **params):
        app = session.panel_application(params)
        if app.status != c.ACCEPTED:
            raise HTTPRedirect(
                'index?message={}', 'You cannot associate a non-accepted panel application with an event')

        elif app.event_id and cherrypy.request.method == 'GET':
            raise HTTPRedirect(
                'index?message={}{}', 'This panel application is already associated with the event ', app.event.name)

        if cherrypy.request.method == 'POST':
            if not app.event_id:
                message = 'You must select an event'
            else:
                for attendee in app.matched_attendees:
                    assigned_panelist = session.query(AssignedPanelist).filter_by(
                        event_id=app.event_id, attendee_id=attendee.id).first()

                    if not assigned_panelist:
                        app.event.assigned_panelists.append(AssignedPanelist(attendee=attendee))
                raise HTTPRedirect('index?message={}{}{}', app.name, ' was associated with ', app.event.name)

        return {
            'app': app,
            'message': message,
            'panels': session.query(Event).filter(Event.location.in_(c.PANEL_ROOMS)).order_by('name')
        }

    def badges(self, session):
        possibles = session.possible_match_list()

        applicants = []
        for pa in session.panel_applicants():
            if not pa.attendee_id and pa.application.status == c.ACCEPTED:
                applicants.append([pa, set(possibles[pa.email.lower()] + possibles[pa.first_name, pa.last_name])])

        return {'applicants': applicants}

    @ajax
    def link_badge(self, session, applicant_id, attendee_id):
        ids = []
        try:
            attendee = session.attendee(attendee_id)
            if attendee.badge_type != c.GUEST_BADGE:
                attendee.ribbon = add_opt(attendee.ribbon_ints, c.PANELIST_RIBBON)

            pa = session.panel_applicant(applicant_id)
            applicants = session.query(PanelApplicant).filter_by(
                first_name=pa.first_name, last_name=pa.last_name, email=pa.email)
            for applicant in applicants:
                ids.append(applicant.id)
                applicant.attendee_id = attendee_id

            session.commit()
        except Exception:
            log.error('unexpected error linking panelist to a badge', exc_info=True)
            return {'error': 'Unexpected error: unable to link applicant to badge.'}
        else:
            return {
                'linked': ids,
                'name': pa.full_name
            }

    @ajax
    def create_badge(self, session, applicant_id):
        ids = []
        try:
            pa = session.panel_applicant(applicant_id)
            attendee = Attendee(
                placeholder=True,
                paid=c.NEED_NOT_PAY,
                ribbon=c.PANELIST_RIBBON,
                badge_type=c.ATTENDEE_BADGE,
                first_name=pa.first_name,
                last_name=pa.last_name,
                email=pa.email,
                cellphone=pa.cellphone
            )
            session.add(attendee)

            applicants = session.query(PanelApplicant).filter_by(
                first_name=pa.first_name, last_name=pa.last_name, email=pa.email)
            for applicant in applicants:
                ids.append(applicant.id)
                applicant.attendee_id = attendee.id
            session.commit()
        except Exception:
            log.error('unexpected error adding new panelist', exc_info=True)
            return {'error': 'Unexpected error: unable to add attendee'}
        else:
            return {'added': ids}

    def panel_feedback(self, session, event_id, **params):
        feedback = session.query(EventFeedback).filter_by(
            event_id=event_id, attendee_id=session.admin_attendee().id).first()
        if params or not feedback:
            feedback = session.event_feedback(params)

        if cherrypy.request.method == 'POST':
            feedback.event_id = event_id
            feedback.headcount_during = feedback.headcount_during or 0
            feedback.headcount_starting = feedback.headcount_starting or 0
            if not feedback.attendee_id:
                feedback.attendee_id = session.admin_attendee().id

            session.add(feedback)
            raise HTTPRedirect('../schedule/form?id={}&message={}', event_id, 'Feedback saved')

        return {
            'feedback': feedback,
            'event': session.event(event_id)
        }

    def feedback_report(self, session):
        feedback = defaultdict(list)
        all_feedback = session.query(EventFeedback).options(
            joinedload(EventFeedback.event), joinedload(EventFeedback.attendee))
        for fb in all_feedback:
            feedback[fb.event].append(fb)

        events = []
        for event in session.query(Event).filter(Event.location.in_(c.PANEL_ROOMS)).order_by('name'):
            events.append([event, feedback[event]])

        for event, fb in feedback.items():
            if event.location not in c.PANEL_ROOMS:
                events.append([event, fb])

        return {'events': events}

    @csv_file
    def panels_by_poc(self, out, session, poc_id):
        attendee = session.attendee(poc_id)
        out.writerow(['', 'Panels for which {} is the panel staff point-of-contact'.format(attendee.full_name)])
        out.writerow(['App status', 'Panel Name', 'Panel Location', 'Panel Time', 'Panelists'])
        for app in attendee.panel_applications:
            out.writerow([
                getattr(app.event, 'status', app.status_label),
                getattr(app.event, 'name', app.name),
                getattr(app.event, 'location_label', '(not scheduled)'),
                app.event.timespan(minute_increment=30) if app.event else '(not scheduled)',
                '\n'.join([
                    '{} ({}) {}'.format(
                        a.full_name,
                        a.email,
                        getattr(a.attendee, 'cellphone', '') or a.cellphone
                    ) for a in app.applicants
                ])
            ])

    @csv_file
    def everything(self, out, session):
        out.writerow([
            'Panel Name',
            'Description',
            'Expected Length',
            'Unavailability',
            'Past Attendance',
            'Affiliations',
            'Type of Panel',
            'Tabletop?',
            'Technical Needs',
            'Applied',
            'Panelists'])

        for app in session.panel_apps():
            panelists = []
            for panelist in app.applicants:
                panelists.extend([
                    panelist.full_name,
                    panelist.email,
                    panelist.cellphone
                ])
            out.writerow([
                app.name,
                app.description,
                app.length_label,
                app.unavailable,
                app.past_attendance,
                app.affiliations,
                app.other_presentation if app.presentation == c.OTHER else app.presentation_label,
                app.tabletop,
                ' / '.join(app.tech_needs_labels) + (' / ' if app.other_tech_needs else '') + app.other_tech_needs,
                app.applied.strftime('%Y-%m-%d')
            ] + panelists)

    def panel_poc_schedule(self, session, attendee_id):
        attendee = session.attendee(attendee_id)
        event_times = defaultdict(lambda: defaultdict(lambda: (1, '')))
        for app in attendee.panel_applications:
            if app.event is not None:
                event_times[app.event.start_time][app.event.location_label] = (app.event.duration, app.event.name)

        schedule = []
        locations = sorted(set(sum([list(locations) for locations in event_times.values()], [])))
        if event_times:
            when = min(event_times)
            while when <= max(event_times):
                schedule.append([when, [event_times[when][where] for where in locations]])
                when += timedelta(minutes=30)

        return {
            'attendee': attendee,
            'schedule': schedule,
            'locations': locations
        }
