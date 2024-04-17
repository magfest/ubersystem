from celery import Celery
from celery.signals import after_setup_logger, beat_init, worker_process_init

from uber.config import _config as config_dict
from uber.models import Session


__all__ = ['celery']


celery = Celery('tasks')
celery.conf.beat_schedule = {}
celery.conf.beat_startup_tasks = []
celery.conf.update(config_dict['celery'])

broker_url = config_dict['secret']['broker_url']

celery.conf.update(result_backend_transport_options={
    'global_prefix': config_dict['secret']['broker_prefix']
})
celery.conf.update(broker_url=broker_url)
celery.conf.update(result_backend=broker_url.replace("amqps://", "rpc://").replace("amqp://", "rpc://"))
celery.conf.update(task_ignore_result=True)


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


from uber.tasks import attractions  # noqa: F401, E402
from uber.tasks import email  # noqa: F401, E402
from uber.tasks import groups  # noqa: F401, E402
from uber.tasks import health  # noqa: F401, E402
from uber.tasks import mivs  # noqa: F401, E402
from uber.tasks import panels  # noqa: F401, E402
from uber.tasks import redis  # noqa: F401, E402
from uber.tasks import registration  # noqa: F401, E402
from uber.tasks import sms  # noqa: F401, E402
