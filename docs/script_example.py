## This is an example of how to set up a script to run against a database, should you need to do so.
## It should have everything you need to get started

from uber.config import c
from uber.models import Attendee, initialize_db, Session

with Session() as session:
    initialize_db()
    session = Session()