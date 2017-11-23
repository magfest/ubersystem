from sideboard.lib import DaemonTask
from uber.decorators import timed, swallow_exceptions
from datetime import datetime
import time
import schedule


class UberSchedulerJob(schedule.Job):
    def do(self, job_func, *args, **kwargs):
        # our scheduler needs to not let individual tasks throw exceptions, so wrap it here
        wrapped_fn = timed(swallow_exceptions(job_func))

        return super().do(wrapped_fn, *args, **kwargs)


class UberScheduler(schedule.Scheduler):
    def every(self, interval=1):
        # use our custom jobs class
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


def run_pending_tasks():
    # we wait a couple minutes after system startup to allow any scheduled tasks to run
    # this is because starting up is CPU intensive and we want the web interface to be responsiv first
    global _startup_time
    if not _startup_time.enough_time_passed():
        return

    schedule.run_pending()
    time.sleep(1)


DaemonTask(run_pending_tasks, interval=1, name="scheduled tasks")


