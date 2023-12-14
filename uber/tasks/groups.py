from collections import defaultdict
from datetime import datetime, timedelta

import stripe
import time
import pytz
from celery.schedules import crontab
from pockets.autolog import log
from sqlalchemy import not_, or_
from sqlalchemy.orm import joinedload
from sqlalchemy.orm.exc import NoResultFound

from uber.config import c
from uber.decorators import render
from uber.models import ApiJob, Attendee, Email, Group, Session, ReceiptTransaction
from uber.tasks.email import send_email
from uber.tasks import celery
from uber.utils import localized_now, TaskUtils, SignNowRequest
from uber.payments import ReceiptManager


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


@celery.schedule(crontab(minute=0, hour='*/1'))
def convert_declined_groups():
    from uber.site_sections.dealer_admin import decline_and_convert_dealer_group

    with Session() as session:
        declined_groups = session.query(Group).filter(Group.status == c.DECLINED,
                                                      Group.badges_purchased > 0)
        for group in declined_groups:
            result = decline_and_convert_dealer_group(session, group, delete_group=c.DELETE_DECLINED_GROUPS)
            log.debug(f"{group.name} converted: {result}")