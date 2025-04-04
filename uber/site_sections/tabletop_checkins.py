from sqlalchemy import func
from sqlalchemy.orm import joinedload, subqueryload
from sqlalchemy.sql import label

from uber.decorators import ajax, ajax_gettable, all_renderable, csv_file
from uber.models import Attendee, BadgeInfo, TabletopCheckout, TabletopGame
from uber.utils import localized_now


@all_renderable()
class Root:
    def index(self, session):
        return {
            'games': _games(session),
            'attendees': _attendees(session)
        }

    def checkout_history(self, session, id):
        return {
            'game': session.tabletop_game(id),
        }

    @csv_file
    def checkout_counts(self, out, session):
        out.writerow([
            'Game Code',
            'Game Name',
            '# Checkouts',
        ])

        tt_games_and_counts = session.query(
            TabletopGame, label('checkout_count', func.count(TabletopCheckout.id)),
        ).outerjoin(TabletopGame.checkouts).group_by(TabletopGame.id).all()

        all_checkouts_count = 0
        for result in tt_games_and_counts:
            game = result[0]
            all_checkouts_count += result.checkout_count
            out.writerow([
                game.code,
                game.name,
                result.checkout_count,
            ])
        out.writerow([
            'N/A',
            'All Games',
            all_checkouts_count,
        ])

    @ajax_gettable
    def badged_attendees(self, session):
        return _attendees(session)

    @ajax
    def add_game(self, session, code, name, attendee_id):
        session.add(TabletopGame(code=code, name=name, attendee_id=attendee_id))
        session.commit()
        return {
            'message': 'Success!',
            'games': _games(session)
        }

    @ajax
    def checkout(self, session, game_id, attendee_id):
        session.add(TabletopCheckout(game_id=game_id, attendee_id=attendee_id))
        session.commit()
        return {
            'message': 'Success!',
            'games': _games(session)
        }

    @ajax
    def returned(self, session, game_id):
        try:
            session.tabletop_game(game_id).checked_out.returned = localized_now()
            session.commit()
        except Exception:
            pass
        return {
            'message': 'Success!',
            'games': _games(session)
        }

    @ajax
    def return_to_owner(self, session, game_id):
        session.tabletop_game(game_id).returned = True
        session.commit()
        return {
            'message': 'Success!',
            'games': _games(session)
        }


def _attendees(session):
    return [{
        'id': id,
        'name': name,
        'badge': num
    } for (id, name, num) in session.query(Attendee.id, Attendee.full_name, BadgeInfo.ident).join(Attendee.active_badge)
                                    .order_by(BadgeInfo.ident).all()]


def _attendee(a):
    return a and {
        'id': a.id,
        'name': a.full_name,
        'badge': a.badge_num
    }


def _checked_out(co):
    return co and {
        'checked_out': co.checked_out,
        'attendee': _attendee(co.attendee)
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
    } for g in session.query(TabletopGame)
                      .options(joinedload(TabletopGame.attendee),
                               subqueryload(TabletopGame.checkouts))
                      .order_by(TabletopGame.name).all()]
