from uber.common import *


@entry_point
def print_config():
    """
    print all config values to stdout, used for debugging / status checking
    useful if you want to verify that Ubersystem has pulled in the INI values you think it has.
    """
    from uber.config import _config
    pprint(_config.dict())


@entry_point
def insert_admin():
    with Session() as session:
        attendee = Attendee(
            placeholder=True,
            first_name='Test',
            last_name='Developer',
            email='magfest@example.com',
            badge_type=c.ATTENDEE_BADGE,
        )
        session.add(attendee)
        session.add(AdminAccount(
            attendee=attendee,
            access=','.join(str(level) for level, name in c.ACCESS_OPTS),
            hashed=bcrypt.hashpw('magfest', bcrypt.gensalt())
        ))


@entry_point
def reset_uber_db():
    assert c.DEV_BOX, 'reset_uber_db is only available on development boxes'
    Session.initialize_db(drop=True, modify_tables=True)
    insert_admin()
