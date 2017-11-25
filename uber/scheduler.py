from sideboard.lib import DaemonTask, on_startup
from uber.decorators import timed, swallow_exceptions
from datetime import datetime
import time
import schedule
from collections import defaultdict

# don't start the email sending in the main thread. everything else is cool.
# NOTE: only applies to cherrypy process ONLY, doesn't apply when started via 'sep' or other processes.
# uncomment this if you want to do email sending in its own process
# _default_cherrypy_exclude_categories = ["automated_email_sending"]
_default_cherrypy_exclude_categories = None


class UberSchedulerJob(schedule.Job):
    def do(self, job_func, *args, **kwargs):
        # our scheduler needs to not let individual tasks throw exceptions, so wrap it here
        wrapped_fn = timed(swallow_exceptions(job_func))

        return super().do(wrapped_fn, *args, **kwargs)


class UberScheduler(schedule.Scheduler):
    def every(self, interval=1):
        # use our custom jobs class so we can override do()
        job = UberSchedulerJob(interval, self)
        return job


schedule.default_scheduler = UberScheduler()


class TimePassed:
    def __init__(self, minutes_to_wait):
        assert minutes_to_wait > 0
        self.minutes_to_wait = minutes_to_wait
        self.create_time = datetime.utcnow()

    def enough_time_passed(self):
        assert self.create_time
        return (datetime.utcnow() - self.create_time).seconds > self.minutes_to_wait*60


_startup_time = TimePassed(2)


def schedule_N_times_per_day(times_per_day, fn, *args, **kwargs):
    # slightly hacky.
    # issue: what we want to say something like "run these every 6 hours starting at midnight"
    # schedule module only supports saying "run every 6 hours from server startup" so the scheduling
    # is dependent on the server runtime, and the schedule isn't consistent based on server start time.
    #
    # work around this by creating multiple copies of the same task, scheduled for different times.
    # CAUTION: if tasks are extremely long-running (more than 1 hour each), they can overlap each other

    hourly_interval = divmod(24, times_per_day)
    assert hourly_interval[1] == 0, "times_per_day must be evenly divisble by 24 hours"
    hourly_interval = hourly_interval[0]

    for hour in range(0,24,int(24/times_per_day)):
        assert 0 <= hour < 24
        _time = "{:02d}:00".format(hour)
        schedule.every().day.at(_time).do(fn, *args, **kwargs)


def run_pending_tasks():
    # we wait a couple minutes after system startup to allow any scheduled tasks to run
    # this is because starting up is CPU intensive and we want the web interface to be responsive first
    global _startup_time, _started_from_cherrypy
    if _started_from_cherrypy and not _startup_time.enough_time_passed():
        return

    schedule.run_pending()
    time.sleep(1)


_task_registrations = defaultdict(list)
_scheduler_daemon = None
_started_from_cherrypy = False

@on_startup
def scheduler_on_cherrypy_startup():
    global _started_from_cherrypy
    _started_from_cherrypy = True
    _start_scheduler(exclude_categories=_default_cherrypy_exclude_categories)


def register_task(fn, category):
    _task_registrations[category].append(fn)


def start_scheduler_and_block(include_categories=None, exclude_categories=None):
    """
    Starts up the scheduler thread and blocks until its finished running.
    Don't use from Cherrypy, only use when starting scheduler from another process
    """
    _start_scheduler(include_categories, exclude_categories)
    while _scheduler_daemon.running:
        time.sleep(1)


def _start_scheduler(include_categories=None, exclude_categories=None):
    """
    Args:
        include_categories: If not None, then only schedule tasks that match these categories
        exclude_categories: List of schedule task categories to exclude

    Returns:

    """
    global _scheduler_daemon
    assert not _scheduler_daemon

    for category, register_fns in _task_registrations.items():
        if all([
            include_categories is None or category in include_categories,
            exclude_categories is None or category not in exclude_categories
        ]):
            for register_fn in register_fns:
                register_fn()

    _scheduler_daemon = DaemonTask(run_pending_tasks, interval=1, name="scheduled tasks")
    _scheduler_daemon.start()  # not needed if called after cherrypy startup event. needed if called before that.



