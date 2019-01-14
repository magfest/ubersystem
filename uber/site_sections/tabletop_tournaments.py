from pockets.autolog import log

from sqlalchemy import func
from sqlalchemy.orm import joinedload, subqueryload
from sqlalchemy.sql import label

from uber.config import c
from uber.decorators import ajax, all_renderable, csv_file
from uber.models import Attendee, Event, TabletopEntrant, TabletopTournament


@all_renderable(c.CHECKINS)
class Root:
    def index(self, session):
        return {'state': _state(session)}

    @csv_file
    def tournament_counts(self, out, session):
        out.writerow([
            'Tournament Name/Time',
            '# of Entrants',
            'Badge #'
        ])
        tournaments = session.query(
            TabletopTournament, label('num_entrants', func.count(TabletopEntrant.id))
        ).join(TabletopTournament.entrants).group_by(TabletopTournament.id)
        for tournament in tournaments:
            for entrant in tournament.entrants:
                out.writerow([
                    '{} ({})'.format(tournament.name, tournament.event.start_time_local.strftime('%-I:%M %p %A')),
                    tournament.num_entrants,
                    entrant.attendee.badge_num if entrant.attendee else 'N/A',
                ])

    @ajax
    def refresh(self, session):
        return {'state': _state(session)}

    @ajax
    def create_tournament(self, session, name, event_id):
        try:
            session.add(TabletopTournament(name=name, event_id=event_id))
            session.commit()
        except Exception:
            session.rollback()
            return {'error': 'That tournament already exists'}
        else:
            return {
                'message': 'Tournament Created',
                'state': _state(session)
            }

    @ajax
    def sign_up(self, session, tournament_id, attendee_id, cellphone):
        from uber import model_checks as umc
        if umc._invalid_phone_number(cellphone):
            return {'error': 'That is not a valid phone number'}
        try:
            attendee = session.attendee(attendee_id)
            attendee.cellphone = cellphone
            session.add(TabletopEntrant(attendee_id=attendee_id, tournament_id=tournament_id))
            session.commit()
        except Exception:
            session.rollback()
            log.error(
                'unable to add tournament entrant tournament={} attendee={}', tournament_id, attendee_id, exc_info=True)
            return {'error': 'That attendee is already signed up for that tournament'}
        else:
            return {
                'message': 'Attendee signed up',
                'state': _state(session)
            }

    @ajax
    def drop(self, session, attendee_id, tournament_id):
        try:
            session.delete(session.tabletop_entrant(attendee_id=attendee_id, tournament_id=tournament_id))
            session.commit()
        except Exception:
            log.error('unable to drop tournament entrant', exc_info=True)

        return {
            'message': 'Entrant dropped; if re-added they will be re-texted',
            'state': _state(session)
        }


def _state(session):
    return {
        'events': _events(session),
        'attendees': _attendees(session),
        'tournaments': _tournaments(session),
    }


def _events(session):
    return [{
        'id': e.id,
        'name': e.name,
        'when': e.start_time_local.strftime('%-I:%M %p %A')
    } for e in session.query(Event)
                      .filter(Event.location.in_(c.TABLETOP_LOCATIONS))
                      .order_by('start_time').all()]


def _attendees(session):
    attendees = session.query(Attendee.id, Attendee.full_name, Attendee.badge_num, Attendee.cellphone) \
        .filter(Attendee.badge_num != 0).order_by(Attendee.badge_num).all()

    return [{
        'id': id,
        'name': name.title(),
        'badge': num,
        'cellphone': cellphone
    } for (id, name, num, cellphone) in attendees]


def _tournaments(session):
    return [{
        'id': t.id,
        'name': t.name,
        'when': t.event.start_time_local.timestamp(),
        'when_display': t.event.start_time_local.strftime('%-I:%M %p %A'),
        'entrants': [{
            'id': te.attendee_id,  # TODO: use entrant.id and entrant.attendee_id instead
            'name': te.attendee.full_name,
            'badge': te.attendee.badge_num,
            'confirmed': te.confirmed
        } for te in sorted(t.entrants, key=lambda e: e.signed_up)]
    } for t in session.query(TabletopTournament)
                      .options(joinedload(TabletopTournament.event),
                               subqueryload(TabletopTournament.entrants).subqueryload(TabletopEntrant.attendee))
                      .order_by('start_time').all()]
