from celery import Celery
from celery.signals import beat_init, worker_process_init

from uber.models import Session


__all__ = ['celery']


celery = Celery('tasks', broker='pyamqp://guest@localhost//')
celery.conf.beat_schedule = {}
celery.conf.beat_startup_tasks = []


def celery_on_startup(fn, *args, **kwargs):
    celery.conf.beat_startup_tasks.append((celery.task(fn), args, kwargs))


def celery_schedule(schedule, *args, **kwargs):
    def _decorator(fn):
        task = celery.task(fn)
        celery.conf.beat_schedule[task.name] = {
            'task': task.name,
            'schedule': schedule,
            'args': args,
            'kwargs': kwargs,
        }
        return task
    return _decorator


celery.on_startup = celery_on_startup
celery.schedule = celery_schedule


@worker_process_init.connect
def init_worker_process(*args, **kwargs):
    Session.initialize_db(initialize=True)


@beat_init.connect
def run_startup_tasks(*args, **kwargs):
    for fn, a, kw in celery.conf.beat_startup_tasks:
        fn.delay(*a, **kw)


from uber.tasks import attractions  # noqa: F401
from uber.tasks import email  # noqa: F401
from uber.tasks import mivs  # noqa: F401
from uber.tasks import registration  # noqa: F401
from uber.tasks import sms  # noqa: F401
from uber.tasks import tabletop  # noqa: F401
