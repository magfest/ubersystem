from datetime import timedelta
import logging
from sqlalchemy.orm import joinedload

from uber.config import c
from uber.decorators import render
from uber.models import Email, Session, GuestGroup, Group, IndieStudio, IndieJudge, IndieGame, IndieGameReview
from uber.tasks import celery
from uber.tasks.email import send_email

log = logging.getLogger(__name__)


__all__ = ['assign_all_games_showcases', 'mivs_assign_game_codes_to_judges', 'send_mivs_checklist_reminders']


@celery.schedule(timedelta(hours=1))
def assign_all_games_showcases():
    if not c.PRE_CON:
        return
    
    with Session() as session:
        games_by_showcase = {}
        for showcase in c.SHOWCASE_GAME_TYPES.keys():
            games_by_showcase[showcase] = session.query(IndieGame).filter(IndieGame.showcase_type == showcase).all()

        for judge in session.query(IndieJudge).filter(IndieJudge.all_games_showcases != None,
                                                      IndieJudge.status == c.CONFIRMED).options(
                                                          joinedload(IndieJudge.reviews)):
            existing_reviews = [review.game_id for review in judge.reviews]
            for showcase in judge.all_games_showcases_ints:
                for game in games_by_showcase[showcase]:
                    if game.id not in existing_reviews:
                        session.add(IndieGameReview(game_id=game.id, judge_id=judge.id))
        session.commit()


@celery.schedule(timedelta(minutes=5))
def mivs_assign_game_codes_to_judges():
    if not c.PRE_CON:
        return

    with Session() as session:
        for game in session.indie_games():
            if game.code_type == c.NO_CODE or game.unlimited_code:
                continue

            for review in game.reviews:
                if not set(game.codes).intersection(review.judge.codes):
                    for code in game.codes:
                        if not code.judge_id:
                            code.judge = review.judge
                            session.commit()
                            break
                    else:
                        log.warning(
                            f'Unable to find free code for game {game.title} to assign to judge {review.judge.full_name}')


def should_send_reminder(session, studio, keys, ident_prepend):
    sent_email_idents = [item[0][len(ident_prepend):] for item in
                         session.query(Email.ident).filter(Email.ident.startswith(ident_prepend),
                                                           Email.fk_id == studio.id)]
    already_reminded = set()
    for ident in sent_email_idents:
        keys = ident.split('_AND_')
        already_reminded.update(keys)
    return set(keys).difference(already_reminded)


@celery.schedule(timedelta(hours=6))
def send_mivs_checklist_reminders():
    if not c.PRE_CON:
        return

    with Session() as session:
        studios = session.query(IndieStudio).join(Group).join(GuestGroup)
        for studio in studios:
            if studio.group and studio.group.guest:
                due_soon, overdue = studio.checklist_items_due_soon_grouped
                due_soon_keys = [key for key, val in due_soon]
                overdue_keys = [key for key, val in overdue]
                from_email, folder = c.INDIE_SHOWCASE_EMAIL, 'mivs'

                if studio.group.guest.matches_showcases([c.MIVS]):
                    from_email, folder = c.MIVS_EMAIL, 'mivs'
                elif studio.group.guest.matches_showcases([c.INDIE_ARCADE]):
                    from_email, folder = c.INDIE_ARCADE_EMAIL, 'indie_arcade'
                elif studio.group.guest.matches_showcases([c.INDIE_RETRO]):
                    from_email, folder = c.INDIE_RETRO_EMAIL, 'indie_retro'

                if due_soon and should_send_reminder(session, studio, due_soon_keys, 'mivs_checklist_reminder_'):
                    send_email.delay(
                        from_email,
                        studio.email,
                        f"You have {len(due_soon_keys)} checklist "
                        f"item{'s' if len(due_soon_keys) > 1 else ''} due soon",
                        render(f'emails/{folder}/checklist_reminder.txt', {'due_soon': due_soon, 'studio': studio},
                               encoding=None),
                        model=studio.to_dict(),
                        ident='mivs_checklist_reminder_' + '_AND_'.join(due_soon_keys)
                    )
                if overdue and should_send_reminder(session, studio, overdue_keys, 'mivs_checklist_overdue_'):
                    send_email.delay(
                        from_email,
                        studio.email,
                        f"You have {len(overdue_keys)} checklist "
                        f"item{'s' if len(overdue_keys) > 1 else ''} overdue!",
                        render(f'emails/{folder}/checklist_reminder.txt', {'overdue': overdue, 'studio': studio},
                               encoding=None),
                        model=studio.to_dict(),
                        ident='mivs_checklist_overdue_' + '_AND_'.join(overdue_keys)
                    )
