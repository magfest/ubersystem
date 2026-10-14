
import json
import re
import logging
from dateutil import parser as dateparser
from datetime import datetime, timedelta
from sqlalchemy import any_

from uber.config import c, AWSSecretFetcher
from uber.tasks import celery

log = logging.getLogger(__name__)


__all__ = ['check_task_progress', 'expire_processed_saml_assertions', 'set_signnow_key', 'update_shirt_counts', 'update_problem_names']


def check_task_progress(redis_key, task_name, delete_locked=False):
    # Returns true if the task is in progress, otherwise false
    task_status = c.REDIS_STORE.hgetall(c.REDIS_PREFIX + redis_key)
    if task_status:
        started_timestamp = task_status['started_timestamp']
        started_time = datetime.fromtimestamp(float(started_timestamp))
        last_warning = task_status.get('warning_timedelta', 0)
        if started_time + timedelta(hours=last_warning + 2) < datetime.now():
            log.error(f"The {task_name} task has taken more than {last_warning + 2} hours. There may be an issue with this task.")
            if delete_locked:
                c.REDIS_STORE.delete(c.REDIS_PREFIX + redis_key)
                return False
            else:
                c.REDIS_STORE.hset(c.REDIS_PREFIX + redis_key, 'warning_timedelta', last_warning + 2)
        return True
    return False


@celery.schedule(timedelta(minutes=30))
def expire_processed_saml_assertions():
    if not c.SAML_SETTINGS:
        return

    rsession = c.REDIS_STORE.pipeline()

    for key, val in c.REDIS_STORE.hscan(c.REDIS_PREFIX + 'processed_saml_assertions')[1].items():
        if int(val) < datetime.now(UTC).timestamp():
            rsession.hdel(c.REDIS_PREFIX + 'processed_saml_assertions', key)

    rsession.execute()


@celery.schedule(timedelta(15))
def set_signnow_key():
    if not c.AWS_SIGNNOW_SECRET_NAME or not c.SIGNNOW_DEALER_TEMPLATE_ID:
        return

    signnow_access_key = c.REDIS_STORE.get(c.REDIS_PREFIX + 'signnow_access_token')
    expired = c.REDIS_STORE.expiretime(c.REDIS_PREFIX + 'signnow_access_token')
    if not signnow_access_key or expired < 0:
        signnow_secret = AWSSecretFetcher().get_signnow_secret()
        if not signnow_secret:
            log.error("Attempted to update our SignNow token but we didn't get a secret back from AWS!")
        c.REDIS_STORE.set(c.REDIS_PREFIX + 'signnow_access_token', signnow_secret.get('ACCESS_TOKEN', ''))
        expire_date = dateparser.parse(signnow_secret.get('LAST_UPDATE', '')[:-6]) + timedelta(hours=23)
        c.REDIS_STORE.expireat(c.REDIS_PREFIX + 'signnow_access_token', int(expire_date.timestamp()))


@celery.schedule(timedelta(seconds=30))
def update_shirt_counts():
    if not c.PRE_CON:
        return

    rsession = c.REDIS_STORE.pipeline()

    for shirt_enum_key in c.PREREG_SHIRTS.keys():
        count = c.get_shirt_count(shirt_enum_key)
        rsession.hset(c.REDIS_PREFIX + 'shirt_counts', shirt_enum_key, count)
        size_stock = c.SHIRT_SIZE_STOCKS.get(shirt_enum_key, None)

        if size_stock is not None and count >= size_stock:
            rsession.sadd(c.REDIS_PREFIX + 'sold_out_shirt_sizes', shirt_enum_key)
        else:
            rsession.srem(c.REDIS_PREFIX + 'sold_out_shirt_sizes', shirt_enum_key)

    rsession.execute()

@celery.schedule(timedelta(minutes=15))
def update_problem_names():
    return
    from uber.models import Attendee, Session

    posix_regex_list = []
    python_regex_dict = {}

    # We want to generally match against word boundaries, but this excludes some creative forms of profanity
    # from being matched, so we also check against whitespace (or beginning/end of string) manually
    for word in c.PROBLEM_NAMES:
        posix_regex_list.append(f"(\\s|^){word}(\\s|$)")
        posix_regex_list.append(f"\\y{word}\\y")
        python_regex_dict[f"(\\s|^){word}(\\s|$)"] = word
        python_regex_dict[f"\\b{word}\\b"] = word

    rsession = c.REDIS_STORE.pipeline()

    with Session() as session:
        attendees = session.query(Attendee).filter(Attendee.badge_printed_name.regexp_match(any_(posix_regex_list),
                                                                                            flags="i")).all()

        attendee_ids = [attendee.id for attendee in attendees]
        current_problem_names = c.REDIS_STORE.smembers(c.REDIS_PREFIX + 'problem_name_ids')
        no_longer_problems = set(current_problem_names) - set(attendee_ids)
        for id in no_longer_problems:
            rsession.hdel(c.REDIS_PREFIX + 'word_matches', id)
            rsession.hdel(c.REDIS_PREFIX + 'origin_words', id)

        for id in attendee_ids:
            rsession.sadd(c.REDIS_PREFIX + 'problem_name_ids', id)

        for attendee in attendees:
            word_match_list = []
            origin_match_list = []
            for regex in python_regex_dict:
                if re.search(re.compile(regex, re.IGNORECASE), attendee.badge_printed_name):
                    found_word = python_regex_dict[regex]
                    if found_word not in word_match_list:
                        word_match_list.append(found_word)
                    for origin_word in c.PROBLEM_NAMES[found_word]:
                        if origin_word not in origin_match_list:
                            origin_match_list.append(origin_word)

            rsession.hset(c.REDIS_PREFIX + 'word_matches', attendee.id, json.dumps(word_match_list))
            rsession.hset(c.REDIS_PREFIX + 'origin_words', attendee.id, json.dumps(origin_match_list))

    rsession.execute()