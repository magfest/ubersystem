import pytz

from datetime import datetime, timedelta
from celery.schedules import crontab
from pockets.autolog import log
from sqlalchemy.orm.exc import NoResultFound

from uber.config import c
from uber.decorators import render
from uber.models import Group, GuestGroup, GuestMerch, Session
from uber.tasks import celery
from uber.tasks.email import send_email
from uber.utils import SignNowRequest, localized_now


__all__ = ['check_document_signed', 'convert_declined_groups']


@celery.schedule(crontab(minute=0, hour='*/6'))
def check_document_signed():
    from uber.models import SignedDocument
    if not c.SIGNNOW_DEALER_TEMPLATE_ID:
        return
    with Session() as session:
        for document in session.query(SignedDocument).filter_by(model="Group"):
            if not document.signed:
                try:
                    group = session.group(document.fk_id)
                except NoResultFound:
                    log.debug(f"Signed document {document.id} is dangling, group f{document.fk_id} not found.")
                else:
                    signnow_request = SignNowRequest(session=session, group=group)
                    signed = signnow_request.get_doc_signed_timestamp()
                    if signed:
                        signnow_request.document.signed = datetime.fromtimestamp(int(signed))
                        signnow_link = ''
                        signnow_request.document.link = signnow_link
                        session.add(signnow_request.document)
                        session.commit()


@celery.schedule(timedelta(hours=12))
def convert_declined_groups():
    from uber.site_sections.dealer_admin import decline_and_convert_dealer_group

    with Session() as session:
        declined_groups = session.query(Group).filter(Group.status == c.DECLINED,
                                                      Group.convert_badges == True,
                                                      Group.badges_purchased > 0)
        for group in declined_groups:
            name = group.name
            result = decline_and_convert_dealer_group(session, group, delete_group=c.DELETE_DECLINED_GROUPS)
            log.debug(f"{name} converted: {result}")


@celery.schedule(crontab(minute=0, hour=0))
def rock_island_updates():
    with Session() as session:
        updated_ri_inventories = session.query(GuestGroup).join(
            GuestMerch, GuestGroup.merch).filter(
                GuestMerch.inventory_updated > datetime.now(pytz.UTC) - timedelta(hours=24))
        if updated_ri_inventories.count():
            subject = '{} Rock Island Inventory Updates for {}'.format(c.EVENT_NAME, localized_now().strftime('%Y-%m-%d'))
            body = render('emails/daily_checks/ri_inventory_updates.html', {
                'updated_ri_inventories': updated_ri_inventories,
            }, encoding=None)
            send_email(c.REPORTS_EMAIL, c.ROCK_ISLAND_EMAIL, subject, body, format='html', model='n/a', session=session)