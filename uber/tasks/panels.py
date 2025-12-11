import json
import re

from collections import defaultdict
from datetime import timedelta, datetime
from dateutil import parser as dateparser
from pockets import sluggify
from sqlalchemy import or_

from uber.automated_emails import AutomatedEmailFixture, PanelAppEmailFixture
from uber.config import c
from uber.decorators import render
from uber.models import Email, Session, Tracking, Department, EventLocation, AutomatedEmail
from uber.tasks import celery
from uber.tasks.email import send_email
from uber.utils import GuidebookUtils, localized_now


__all__ = ['panels_waitlist_unaccepted_panels', 'sync_guidebook_models',
           'check_deleted_guidebook_models', 'check_stale_guidebook_models']


def _get_deleted_models(session, deleted_since=None):
    deleted_synced = session.query(Tracking).filter(Tracking.action == c.DELETED,
                                                    Tracking.snapshot.contains('"last_synced": {"data": {"guidebook"'))
    if deleted_since:
        deleted_synced = deleted_synced.filter(Tracking.when > deleted_since)

    deleted_models = defaultdict(list)
    model_names = {}

    for key, label in c.GUIDEBOOK_MODELS:
        model_names[key] = label

    for tracking_entry in deleted_synced:
        snapshot = json.loads(tracking_entry.snapshot)
        guidebook_data = snapshot['last_synced']['data']['guidebook']

        model = snapshot['_model']
        if model == 'GuestGroup':
            model += '_band' if snapshot['group_type'] == c.BAND else '_guest'
        elif model == 'Group':
            model += '_dealer'

        if model == 'Event':
            model_name = 'Schedule Item'
            start_day = datetime.strptime(guidebook_data['start_date'], '%M/%d/%Y').strftime('%A (%-m/%-d/%Y)')
            end_day = datetime.strptime(guidebook_data['end_date'], '%M/%d/%Y').strftime('%A (%-m/%-d/%Y)')
            if start_day != end_day:
                item_name = f"{guidebook_data['name']} on {start_day} {guidebook_data['start_time']} to {end_day} {guidebook_data['end_time']}"
            else:
                item_name = f"{guidebook_data['name']} on {start_day} {guidebook_data['start_time']} to {guidebook_data['end_time']}"
        else:
            model_names[model]
            item_name = guidebook_data['name']

        deleted_models[model_name].append(item_name)
    return deleted_models


@celery.task
def sync_guidebook_models(selected_model, sync_time, id_list):
    with Session() as session:
        query, _ = GuidebookUtils.get_guidebook_models(session, selected_model)
        model = GuidebookUtils.parse_guidebook_model(selected_model)
        query = query.filter(model.id.in_(id_list), model.last_updated < dateparser.parse(sync_time))

        for model in query:
            model.update_last_synced('guidebook', sync_time)
            if not model.last_synced.get('data', {}):
                model.last_synced['data'] = {}
            model.last_synced['data']['guidebook'] = model.guidebook_data
            model.skip_last_updated = True

            session.add(model)
            session.commit()


@celery.schedule(timedelta(hours=1))
def check_deleted_guidebook_models():
    if not c.PRE_CON or not c.GUIDEBOOK_UPDATES_EMAIL:
        return
    
    with Session() as session:
        subject = f"Deleted Guidebook Items: {localized_now().strftime("%A %-I:%M %p")}"
        last_email = session.query(Email).filter(Email.subject.contains("Deleted Guidebook Items")
                                                 ).order_by(Email.when.desc()).first()

        deleted_models = _get_deleted_models(session, deleted_since=last_email.when) if last_email else _get_deleted_models(session)

        if deleted_models:
            body = render('emails/guidebook_deletes.txt', {
                'deleted_models': deleted_models,
            }, encoding=None)
            send_email.delay(c.REPORTS_EMAIL, c.GUIDEBOOK_UPDATES_EMAIL,
                             subject, body, ident="guidebook_deletes"
                             )


@celery.schedule(timedelta(minutes=15))
def check_stale_guidebook_models():
    if not c.AT_THE_CON or not c.GUIDEBOOK_UPDATES_EMAIL:
        return

    with Session() as session:
        cl_updates, schedule_updates = GuidebookUtils.get_changed_models(session)
        stale_models = [key for key in cl_updates if cl_updates[key]]
        if schedule_updates:
            stale_models.append('Schedule')

        last_email = session.query(Email).filter(or_(
            Email.subject.contains("Guidebook Updates"),
            Email.subject.contains("Deleted Guidebook Items"))
            ).order_by(Email.when.desc()).first()

        deleted_models = _get_deleted_models(session, deleted_since=last_email.when) if last_email else _get_deleted_models(session)

        if stale_models or deleted_models:
            body = render('emails/guidebook_updates.txt', {
                'stale_models': stale_models,
                'deleted_models': deleted_models,
            }, encoding=None)
            send_email.delay(c.REPORTS_EMAIL, c.GUIDEBOOK_UPDATES_EMAIL,
                                f"Guidebook Updates: {localized_now().strftime("%A %-I:%M %p")}",
                                body, ident="guidebook_updates"
                                )


@celery.schedule(timedelta(hours=6))
def panels_waitlist_unaccepted_panels():
    from uber.models import PanelApplication
    if not c.PRE_CON or not c.PANELS_CONFIRM_DEADLINE:
        return

    with Session() as session:
        for app in session.query(PanelApplication).filter_by(status=c.ACCEPTED):
            if not app.confirmed and app.after_confirm_deadline:
                app.status = c.WAITLISTED
                session.commit()
                body = render('emails/panels/panel_app_waitlisted.txt', {
                    'app': app,
                }, encoding=None)
                send_email.delay(c.PANELS_EMAIL, app.email,
                                 f"Your {c.EVENT_NAME} Panel Application Has Been Automatically Waitlisted: "
                                 f"{app.name}",
                                 body,
                                 ident="panel_waitlisted",
                                 shared_ident="panelapps_waitlisted"
                                 )


@celery.schedule(timedelta(minutes=30))
def setup_panel_emails():
    if not c.PRE_CON:
        return
    
    with Session() as session:
        panels_depts_query = session.query(Department).filter(Department.manages_panels == True)

        panels_depts = panels_depts_query.filter(Department.from_email != '').all()
        current_depts = [dept.from_email for dept in panels_depts]
        emails_to_add = {dept.from_email: (dept.id, dept.name) for dept in panels_depts}

        current_email_fixtures = session.query(AutomatedEmail).filter(AutomatedEmail.ident.startswith('panelapps_'))

        for fixture in current_email_fixtures:
            if fixture.sender not in [current_depts]:
                AutomatedEmail._fixtures.pop(fixture.ident, None)
            elif fixture.ident in AutomatedEmail._fixtures:
                emails_to_add.pop(fixture.sender, None)

        emails_to_add.pop(c.PANELS_EMAIL, None)

    for email, (id, name) in emails_to_add.items():
        sender = f'{c.EVENT_NAME} {name} <{email}>'

        def custom_panel_app_email(subject, template, filter, ident, dept_id=id, **kwargs):
            PanelAppEmailFixture(
                subject,
                template,
                lambda app: filter(app) and app.department == dept_id,
                ident,
                **kwargs)

        custom_panel_app_email(
            'Your {EVENT_NAME} Panel Application Has Been Received: {{ app.name }}',
            'panels/application.html',
            lambda app: True,
            sender=sender,
            shared_ident='panelapps_received',
            ident=f'panelapps_received_{sluggify(name)}')

        custom_panel_app_email(
            'Your {EVENT_NAME} Panel Application Has Been Accepted: {{ app.name }}',
            'panels/panel_app_accepted.txt',
            lambda app: app.status == c.ACCEPTED,
            sender=sender,
            shared_ident='panelapps_accepted',
            ident=f'panelapps_accepted_{sluggify(name)}')

        custom_panel_app_email(
            'Your {EVENT_NAME} Panel Application Has Been Declined: {{ app.name }}',
            'panels/panel_app_declined.txt',
            lambda app: app.status == c.DECLINED,
            sender=sender,
            shared_ident='panelapps_declined',
            ident=f'panelapps_declined_{sluggify(name)}')

        custom_panel_app_email(
            'Your {EVENT_NAME} Panel Application Has Been Waitlisted: {{ app.name }}',
            'panels/panel_app_waitlisted.txt',
            lambda app: app.status == c.WAITLISTED,
            sender=sender,
            shared_ident='panelapps_waitlisted',
            ident=f'panelapps_waitlisted_{sluggify(name)}')

        custom_panel_app_email(
            'Last chance to confirm your panel',
            'panels/panel_accept_reminder.txt',
            lambda app: (c.PANELS_CONFIRM_DEADLINE and app.confirm_deadline
                         and (localized_now() + timedelta(days=2)) > app.confirm_deadline),
            sender=sender,
            shared_ident='panelapps_accept_reminder',
            ident=f'panelapps_accept_reminder_{sluggify(name)}')

        custom_panel_app_email(
            'Your {EVENT_NAME} Panel Has Been Scheduled: {{ app.name }}',
            'panels/panel_app_scheduled.txt',
            lambda app: app.event_id,
            sender=sender,
            shared_ident='panelapps_scheduled',
            ident=f'panelapps_scheduled_{sluggify(name)}')
    
    AutomatedEmail.reconcile_fixtures()
