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

@entry_point
def add_age_groups():
    with Session() as session:
        age_group = AgeGroup(
            desc           = 'under 13',
            min_age        = 0,
            max_age        = 12,
            discount       = 0,
            can_register   = False
        )
        session.add(age_group)
        
        age_group = AgeGroup(
            desc           = '13 to 18',
            min_age        = 13,
            max_age        = 17,
            discount       = 0,
            can_register   = True
        )
        session.add(age_group)
        
        age_group = AgeGroup(
            desc           = '18 or over',
            min_age        = 18,
            max_age        = 150,
            discount       = 0,
            can_register   = True
        )
        session.add(age_group)
