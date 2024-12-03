from datetime import timedelta
from dateutil import parser as dateparser
from sqlalchemy import or_

from uber.config import c
from uber.decorators import render
from uber.models import Session
from uber.tasks import celery
from uber.tasks.email import send_email
from uber.utils import GuidebookUtils, localized_now


__all__ = ['panels_waitlist_unaccepted_panels', 'sync_guidebook_models', 'check_stale_guidebook_models']


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


@celery.schedule(timedelta(minutes=15))
def check_stale_guidebook_models():
    if not c.AT_THE_CON:
        return

    with Session() as session:
        cl_updates, schedule_updates = GuidebookUtils.get_changed_models(session)
        stale_models = [key for key in cl_updates if cl_updates[key]]
        if schedule_updates:
            stale_models.append('Schedule')
        if stale_models:
            body = render('emails/guidebook_updates.txt', {
                'stale_models': stale_models,
            }, encoding=None)
            send_email.delay(c.REPORTS_EMAIL, "gb-ops@magfest.org",
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
                                 "Your {EVENT_NAME} Panel Application Has Been Automatically Waitlisted: "
                                 "{{ app.name }}",
                                 body, ident="panel_waitlisted"
                                 )
