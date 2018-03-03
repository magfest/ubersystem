import time
from math import modf
from threading import RLock

import schedule
from sideboard.lib import entry_point

from uber.decorators import run_threaded, swallow_exceptions, timed


__all__ = ['schedule', 'run_scheduled_tasks']


class ThreadedJob(schedule.Job):
    def do(self, job_func, *args, threaded=True, thread_name=None, **kwargs):
        thread_name = thread_name or job_func.__name__
        wrapped_func = timed('Finished background thread: ')(swallow_exceptions(job_func))
        if threaded:
            if not job_func.__dict__.get('_lock', None):
                job_func.__dict__['_lock'] = RLock()
            wrapped_func = run_threaded(thread_name, lock=job_func._lock, blocking=False)(wrapped_func)
        return super(ThreadedJob, self).do(wrapped_func, *args, **kwargs)


class ThreadedScheduler(schedule.Scheduler):
    def every(self, interval=1):
        return ThreadedJob(interval, self)


def schedule_n_times_per_day(times_per_day, fn, *args, **kwargs):
    assert 1 <= times_per_day <= 1440
    hours = 24.0 / times_per_day
    jobs = []
    for i in range(times_per_day):
        hour_fraction, hour = modf(hours * i)
        minute = hour_fraction * 60.0
        time_of_day = '{:02.0f}:{:02.0f}'.format(hour, minute)
        jobs.append(schedule.every().day.at(time_of_day).do(fn, *args, **kwargs))
    return jobs


schedule.default_scheduler = ThreadedScheduler()
schedule.n_times_per_day = schedule_n_times_per_day


@entry_point
def run_scheduled_tasks():
    while True:
        schedule.run_pending()
        time.sleep(1)


@entry_point
def run_automated_emails():
    from pprint import pprint
    from uber.tasks.email import SendAutomatedEmailsJob
    SendAutomatedEmailsJob.run()
    pprint(SendAutomatedEmailsJob.last_result)


from uber.tasks import attractions  # noqa: F401
from uber.tasks import email  # noqa: F401
from uber.tasks import mivs  # noqa: F401
from uber.tasks import registration  # noqa: F401
from uber.tasks import tabletop  # noqa: F401


# NOTE: This can be a useful debugging tool :)
# from pockets.autolog import log
# from uber.models import Session
# schedule.every(5).seconds.do(lambda: log.error(Session.engine.pool.status()))
