from datetime import timedelta

from uber.config import c
from uber.decorators import render
from uber.models import Session
from uber.tasks import celery
from uber.tasks.email import send_email


__all__ = ['panels_waitlist_unaccepted_panels']


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
