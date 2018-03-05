import time
from math import modf
from threading import RLock

import schedule
from sideboard.lib import entry_point

from uber.decorators import run_threaded, swallow_exceptions, timed
from uber.models import Session


__all__ = ['schedule', 'run_scheduled_tasks']


def _safety_wrap(fn, threaded=True, thread_name=None):
    thread_name = thread_name or fn.__name__
    wrapped_func = timed('Finished {}: '.format('background thread' if threaded else 'task'))(swallow_exceptions(fn))
    if threaded:
        if not fn.__dict__.get('_lock', None):
            fn.__dict__['_lock'] = RLock()
        wrapped_func = run_threaded(thread_name, lock=fn._lock, blocking=False)(wrapped_func)
    return wrapped_func


class ThreadedJob(schedule.Job):
    def do(self, job_func, *args, threaded=True, thread_name=None, **kwargs):
        wrapped_func = _safety_wrap(job_func, threaded=threaded, thread_name=thread_name)
        return super(ThreadedJob, self).do(wrapped_func, *args, **kwargs)


class ThreadedScheduler(schedule.Scheduler):
    def every(self, interval=1):
        return ThreadedJob(interval, self)


def schedule_n_times_per_day(times_per_day, fn, *args, threaded=True, thread_name=None, **kwargs):
    assert 1 <= times_per_day <= 1440
    hours = 24.0 / times_per_day
    jobs = []
    for i in range(times_per_day):
        hour_fraction, hour = modf(hours * i)
        minute = hour_fraction * 60.0
        time_of_day = '{:02.0f}:{:02.0f}'.format(hour, minute)
        jobs.append(schedule.every().day.at(time_of_day).do(
            fn, *args, threaded=threaded, thread_name=thread_name, **kwargs))
    return jobs


_is_started = False
_startup_tasks = []


def schedule_on_startup(fn, *args, threaded=True, thread_name=None, **kwargs):
    wrapped_func = _safety_wrap(fn, threaded=threaded, thread_name=thread_name)
    if _is_started:
        wrapped_func(*args, **kwargs)
    else:
        _startup_tasks.append((wrapped_func, args, kwargs))


schedule.default_scheduler = ThreadedScheduler()
schedule.n_times_per_day = schedule_n_times_per_day
schedule.on_startup = schedule_on_startup


@entry_point
def run_scheduled_tasks():
    Session.initialize_db(initialize=True)

    global _is_started
    _is_started = True
    for fn, args, kwargs in _startup_tasks:
        fn(*args, **kwargs)

    while True:
        schedule.run_pending()
        time.sleep(1)


@entry_point
def send_automated_emails():
    from pprint import pprint
    from uber.models import AutomatedEmail
    from uber.tasks.email import send_automated_emails as send_emails

    Session.initialize_db(initialize=True)
    AutomatedEmail.reconcile_fixtures()
    pprint(send_emails())


from uber.tasks import attractions  # noqa: F401
from uber.tasks import email  # noqa: F401
from uber.tasks import mivs  # noqa: F401
from uber.tasks import registration  # noqa: F401
from uber.tasks import tabletop  # noqa: F401


# NOTE: This can be a useful debugging tool :)
# from pockets.autolog import log
# from uber.models import Session
# schedule.every(5).seconds.do(lambda: log.error(Session.engine.pool.status()))
