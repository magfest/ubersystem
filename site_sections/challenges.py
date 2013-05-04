from common import *


def relevant(successes):
    successes = sorted(successes, key=lambda s: s.challenge.game)
    for challenge, succs in groupby(successes, lambda s: s.challenge):
        yield max((LEVEL_VALUES[s.level], s) for s in succs)[1]

def points(successes):
    return sum(LEVEL_VALUES[s.level] for s in successes)


@all_renderable(CHALLENGES)
class Root:
    def index(self, success_id="0", message=""):
        all_successes = defaultdict(list)
        for s in Success.objects.all():
            all_successes[s.identifier].append(s)
        
        rankings = [(points(successes), identifier, successes[0].badge_type, successes[0].badge_num)
                    for identifier,successes in all_successes.items()]
        
        return {
            "rankings":   sorted(rankings, reverse=True),
            "challenges": [(c.id,c.game) for c in Challenge.objects.order_by("game")],
            "success_id": int(success_id),
            "message":    message
        }
    
    def record_success(self, return_to="index?", **params):
        success = Success.get(params)
        message = check(success)
        if message:
            raise HTTPRedirect(return_to + "message={}", message)
        
        success.save()
        message = "%s was recorded as completing '%s' on %s" % (success.identifier, success.challenge.game, success.get_level_display())
        raise HTTPRedirect(return_to + "success_id={}&message={}", success.id, message)
    
    def undo(self, success_id):
        Success.objects.filter(id=success_id).delete()
        raise HTTPRedirect("index?message={}", "Success deleted")
    
    def by_attendee(self, badge_type, badge_num, message="", success_id=None):
        successes = Success.objects.filter(badge_type=badge_type, badge_num=badge_num).order_by("level")
        return {
            "identifier":  identifier(badge_type, badge_num),
            "points":      points(successes),
            "successes":   successes,
            "challenges":  [(c.id, c.game) for c in Challenge.objects.order_by("game")],
            "badge_type":  badge_type,
            "badge_num":   badge_num,
            "message":     message
        }
        
    def delete_successes(self, succ_id):
        success = Success.objects.get(id=succ_id)
        success.delete()
        raise HTTPRedirect("by_attendee?badge_type={}&badge_num={}&message={}", success.badge_type, success.badge_num, "Success removed")
    
    def form(self, message=""):
        return {
            "challenges": Challenge.objects.order_by("game"),
            "message":    message
        }
    
    def create(self, **params):
        challenge = Challenge.get(params, bools=["normal","hard","expert"])
        message = check(challenge)
        if message:
            raise HTTPRedirect("form?message={}", message)
        
        challenge.save()
        raise HTTPRedirect("form?message={}", "Challenge created")
    
    def update(self, **params):
        Challenge.get(params, bools=["normal","hard","expert"]).save()
        raise HTTPRedirect("form?message={}", "Challenge updated")
    
    def delete(self, id):
        Challenge.objects.filter(id=id).delete()
        raise HTTPRedirect("form?message={}", "Challenge deleted")
    
    def by_successes(self):
        counts = defaultdict(lambda: defaultdict(int))
        for success in Success.objects.select_related():
            counts[success.level][success.challenge.id] += 1
        
        challenges = []
        for level,field in [(NORMAL,"normal"),(HARD,"hard"),(EXPERT,"expert")]:
            withcounts = [(c,counts[level][c.id]) for c in Challenge.objects.filter(**{field:True})]
            withcounts.sort(lambda x,y: cmp(y[1],x[1]) or cmp(x[0].game,y[0].game))
            challenges.append( [field,withcounts] )
        
        return {"challenges":challenges}
