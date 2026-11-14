import uuid

from uber.config import c
from uber.models import Attendee, Email, WatchList


def test_watchlist_email_names_the_attendee(session):
    entry = WatchList(first_names='Lorraine', last_name=f'Baines{uuid.uuid4().hex[:6]}')
    attendee = Attendee(first_name='Lorraine', last_name=entry.last_name,
                        email=f'{uuid.uuid4().hex}@example.com', watch_list=entry)
    session.add_all([entry, attendee])
    session.flush()

    assert attendee.badge_status == c.WATCHED_STATUS
    email = session.query(Email).filter(Email.ident == 'watchlist_match_admin',
                                        Email.body.contains(attendee.id)).one()
    assert f'Someone named Lorraine {entry.last_name} has just registered' in email.body
