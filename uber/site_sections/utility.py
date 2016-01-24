from uber.common import *

@all_renderable(c.PEOPLE)
class Root:
    def badge_number_consistency_check(self, session, run_check=None, run_fixup=None, submit=None):
        errors = []
        ran_fixup = False
        ran_check = False

        if run_check:
            errors = badge_consistency_check(session)
            ran_check = True

        if submit and run_fixup == "yes, do it":
            if c.SHIFT_CUSTOM_BADGES:
                fixup_all_badge_numbers(session)
                ran_fixup = True
            else:
                errors.append("Can't run the badge fixup because CUSTOM_BADGES_REALLY_ORDERED is True")

        return {
            'errors': errors,
            'ran_fixup': ran_fixup,
            'ran_check': ran_check
        }
