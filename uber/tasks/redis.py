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


__all__ = ['expire_processed_saml_assertions', 'update_shirt_counts']


@celery.schedule(timedelta(minutes=30))
def expire_processed_saml_assertions():
    if not c.SAML_SETTINGS:
        return
    
    rsession = c.REDIS_STORE.pipeline()
    
    for key, val in c.REDIS_STORE.hscan(c.REDIS_PREFIX + 'processed_saml_assertions')[1].items():
        if int(val) < datetime.utcnow().timestamp():
            rsession.hdel(c.REDIS_PREFIX + 'processed_saml_assertions', key)
    
    rsession.execute()


@celery.schedule(timedelta(seconds=30))
def update_shirt_counts():
    if not c.PRE_CON:
        return
    
    rsession = c.REDIS_STORE.pipeline()

    for shirt_enum_key in c.PREREG_SHIRTS.keys():
        count = c.get_shirt_count(shirt_enum_key)
        rsession.hset(c.REDIS_PREFIX + 'shirt_counts', shirt_enum_key, count)
        size_stock = c.SHIRT_SIZE_STOCKS.get(shirt_enum_key, None)

        if size_stock != None and count >= size_stock:
            rsession.sadd(c.REDIS_PREFIX + 'sold_out_shirt_sizes', shirt_enum_key)
        else:
            rsession.srem(c.REDIS_PREFIX + 'sold_out_shirt_sizes', shirt_enum_key)

    rsession.execute()