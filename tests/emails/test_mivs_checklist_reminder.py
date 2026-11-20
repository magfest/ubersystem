import json
import uuid

from uber.config import c
from uber.models import Email, IndieStudio
from uber.tasks.mivs import should_send_reminder


def _studio(session):
    studio = IndieStudio(name=f'Studio {uuid.uuid4().hex[:8]}')
    session.add(studio)
    session.flush()
    return studio


def _reminder(session, studio, **data):
    # EmailHandler stores each render_data value as a JSON string.
    email = Email(model='IndieStudio', fk_id=studio.id, to='studio@example.com', subject='Reminder', body='Body',
                  sender='mivs@example.com', ident='indie_arcade_checklist_reminder', status=c.SENT,
                  render_data={key: json.dumps(val) for key, val in data.items()})
    session.add(email)
    session.flush()
    return email


def test_reminds_about_every_item_when_none_sent(session):
    studio = _studio(session)
    assert should_send_reminder(session, studio, ['hotel_space'], 'overdue') == {'hotel_space'}


def test_skips_items_already_reminded(session):
    studio = _studio(session)
    _reminder(session, studio, overdue=[['hotel_space', 'Hotel Signups']])

    assert should_send_reminder(session, studio, ['hotel_space', 'logistics'], 'overdue') == {'logistics'}


def test_reads_reminders_stored_before_json_encoding(session):
    studio = _studio(session)
    email = _reminder(session, studio)
    email.render_data = {'overdue': [['hotel_space', 'Hotel Signups']]}
    session.flush()

    assert should_send_reminder(session, studio, ['hotel_space', 'logistics'], 'overdue') == {'logistics'}


def test_due_soon_reminder_does_not_cover_overdue(session):
    studio = _studio(session)
    _reminder(session, studio, due_soon=[['hotel_space', 'Hotel Signups']])

    assert should_send_reminder(session, studio, ['hotel_space'], 'overdue') == {'hotel_space'}
