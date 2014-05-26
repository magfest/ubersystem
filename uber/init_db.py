from uber.common import *

def insert_admin():
    attendee = Attendee.objects.create(
        placeholder = True,
        first_name  = 'Test',
        last_name   = 'Developer',
        email       = 'magfest@example.com',
        badge_type  = STAFF_BADGE,
        ribbon      = DEPT_HEAD_RIBBON
    )
    AdminAccount.objects.create(
        attendee = attendee,
        access   = ','.join(str(level) for level, name in ACCESS_OPTS),
        hashed   = bcrypt.hashpw('magfest', bcrypt.gensalt())
    )

@entry_point
def init_db():
    verbose = '--quiet' not in sys.argv
    dry_run = '--dry-run' in sys.argv
    if any(not arg.startswith('-') for arg in sys.argv[1:]):
        classes = [c for c in classes if c.__name__ in sys.argv[1:]]

    drop_and_create()
    if not dry_run:
        insert_admin()
