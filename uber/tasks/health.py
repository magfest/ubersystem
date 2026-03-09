from uber.tasks import celery
from uber.models import ReadonlySession
from sqlalchemy import text


@celery.task(ignore_result=False)
def ping(response):
    with ReadonlySession() as session:
        session.execute(text('SELECT 1'))
    return response
