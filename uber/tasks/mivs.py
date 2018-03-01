from pockets.autolog import log

from uber.config import c
from uber.models import Session
from uber.tasks import schedule


__all__ = ['mivs_assign_game_codes_to_judges']


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


schedule.every(5).minutes.do(mivs_assign_game_codes_to_judges)
