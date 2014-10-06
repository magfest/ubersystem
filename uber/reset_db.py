from uber.common import *

@entry_point
def insert_admin():
    with Session() as session:
        attendee = Attendee(
            placeholder = True,
            first_name  = 'Test',
            last_name   = 'Developer',
            email       = 'magfest@example.com',
            badge_type  = STAFF_BADGE,
            ribbon      = DEPT_HEAD_RIBBON
        )
        session.add(attendee)
        session.add(AdminAccount(
            attendee = attendee,
            access   = ','.join(str(level) for level, name in ACCESS_OPTS),
            hashed   = bcrypt.hashpw('magfest', bcrypt.gensalt())
        ))

@entry_point
def reset_uber_db():
    assert DEV_BOX, 'reset_uber_db is only available on development boxes'
    Session.initialize_db(drop=True)
    insert_admin()
