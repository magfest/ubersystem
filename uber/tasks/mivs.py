from datetime import timedelta

from pockets.autolog import log

from uber.config import c
from uber.decorators import render
from uber.models import Email, Session, GuestGroup, Group, IndieStudio
from uber.tasks import celery
from uber.tasks.email import send_email


__all__ = ['mivs_assign_game_codes_to_judges']


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
                            'Unable to find free code for game {} to assign to judge {}',
                            game.title,
                            review.judge.full_name)


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
                if due_soon and should_send_reminder(session, studio, due_soon_keys, 'mivs_checklist_reminder_'):
                    send_email.delay(
                        c.MIVS_EMAIL,
                        studio.email,
                        f"You have {len(due_soon_keys)} MIVS checklist "
                        f"item{'s' if len(due_soon_keys) > 1 else ''} due soon",
                        render('emails/mivs/checklist_reminder.txt', {'due_soon': due_soon, 'studio': studio},
                               encoding=None),
                        model=studio.to_dict(),
                        ident='mivs_checklist_reminder_' + '_AND_'.join(due_soon_keys)
                    )
                if overdue and should_send_reminder(session, studio, overdue_keys, 'mivs_checklist_overdue_'):
                    send_email.delay(
                        c.MIVS_EMAIL,
                        studio.email,
                        f"You have {len(overdue_keys)} MIVS checklist "
                        f"item{'s' if len(overdue_keys) > 1 else ''} overdue!",
                        render('emails/mivs/checklist_reminder.txt', {'overdue': overdue, 'studio': studio},
                               encoding=None),
                        model=studio.to_dict(),
                        ident='mivs_checklist_overdue_' + '_AND_'.join(overdue_keys)
                    )
