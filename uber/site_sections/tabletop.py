from uber.common import *

def _attendees(session):
    return [{
        'id': id,
        'name': name,
        'badge': num
    } for (id, name, num) in session.query(Attendee.id, Attendee.full_name, Attendee.badge_num)
                                    .filter(Attendee.badge_num != 0)
                                    .order_by(Attendee.badge_num).all()]

def _attendee(a):
    return a and {
        'id': a.id,
        'name': a.full_name,
        'badge': a.badge_num
    }

def _checked_out(c):
    return c and {
        'checked_out': c.checked_out,
        'attendee': _attendee(c.attendee)
    }

def _games(session):
    return [{
        'id': g.id,
        'code': g.code,
        'name': g.name,
        'returned': g.returned,
        'attendee_id': g.attendee_id,
        'attendee': _attendee(g.attendee),
        'checked_out': _checked_out(g.checked_out)
    } for g in session.query(Game).options(joinedload(Game.attendee)).order_by(Game.name).all()]

@all_renderable(CHECKINS)
class Root:
    def index(self, session):
        return {
            'games': _games(session),
            'attendees': _attendees(session)
        }

    @ajax
    def badged_attendees(self, session):
        return _attendees(session)

    @ajax
    def add_game(self, session, code, name, attendee_id):
        session.add(Game(code=code, name=name, attendee_id=attendee_id))
        session.commit()
        return {
            'message': 'Success!',
            'games': _games(session)
        }

    @ajax
    def checkout(self, session, game_id, attendee_id):
        session.add(Checkout(game_id=game_id, attendee_id=attendee_id))
        session.commit()
        return {
            'message': 'Success!',
            'games': _games(session)
        }

    @ajax
    def returned(self, session, game_id):
        try:
            session.game(game_id).checked_out.returned = localized_now()
            session.commit()
        except:
            pass
        return {
            'message': 'Success!',
            'games': _games(session)
        }

    @ajax
    def return_to_owner(self, session, game_id):
        session.game(game_id).returned = True
        session.commit()
        return {
            'message': 'Success!',
            'games': _games(session)
        }
