from collections import defaultdict
from datetime import datetime, timedelta

import stripe
import time
from celery.schedules import crontab
from pockets.autolog import log
from sqlalchemy import not_, or_
from sqlalchemy.orm import joinedload

from uber.config import c
from uber.decorators import render
from uber.models import ApiJob, Attendee, Email, Session, ReceiptTransaction
from uber.tasks.email import send_email
from uber.tasks import celery
from uber.utils import localized_now, TaskUtils
from uber.payments import ReceiptManager


__all__ = ['expire_processed_saml_assertions']


@celery.schedule(timedelta(minutes=30))
def expire_processed_saml_assertions():
    if not c.SAML_SETTINGS:
        return
    
    rsession = c.REDIS_STORE.pipeline()
    
    for key, val in c.REDIS_STORE.hscan('processed_saml_assertions')[1].items():
        if int(val) < datetime.utcnow().timestamp():
            rsession.hdel('processed_saml_assertions', key)
    
    rsession.execute()