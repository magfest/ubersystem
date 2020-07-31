import cherrypy

from uber.config import c
from uber.decorators import ajax, all_renderable, log_pageview
from uber.errors import HTTPRedirect
from uber.models import Attendee, WatchList


@all_renderable()
class Root:
    @log_pageview
    def index(self, session, message='', **params):
        watch_entry = session.watch_list(params, bools=WatchList.all_bools)

        watchlist_entries = session.query(WatchList).order_by(WatchList.last_name).all()
        for entry in watchlist_entries:
            entry.attendee_guesses = session.guess_watchentry_attendees(entry)

        if 'first_names' in params:
            if not watch_entry.first_names and not watch_entry.last_name:
                message = 'A first or last name is required.'
            if not watch_entry.email and not watch_entry.birthdate:
                message = 'Email or date of birth is required.'
            elif not watch_entry.reason or not watch_entry.action:
                message = 'Reason and action are required.'

            if not message:
                session.add(watch_entry)
                if 'id' not in params:
                    message = 'New watch list item added.'
                else:
                    message = 'Watch list item updated.'

                session.commit()

            watch_entry = WatchList()

        return {
            'new_watch': watch_entry,
            'watchlist_entries': watchlist_entries,
            'message': message
        }

    @ajax
    def update_watchlist_entry(self, session, attendee_id, watchlist_id=None, message='', **params):
        attendee = session.attendee(attendee_id, allow_invalid=True)
        if 'ignore' in params:
            attendee.badge_status = c.COMPLETED_STATUS
            message = 'Attendee can now check in'
        elif watchlist_id:
            watchlist_entry = session.watch_list(watchlist_id)

            if 'active' in params:
                watchlist_entry.active = not watchlist_entry.active
                message = 'Watchlist entry updated'
            if 'confirm' in params:
                attendee.watchlist_id = watchlist_id
                message = 'Watchlist entry permanently matched to attendee'

        session.commit()

        return {'success': True, 'message': message}
