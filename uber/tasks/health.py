from uber.tasks import celery
from uber.models import Session
from sqlalchemy import text

@celery.task
def ping(response):
    with Session() as session:
        session.execute(text('SELECT 1'))
    return response