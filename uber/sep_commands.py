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
def resave_all_attendees_and_groups():
    """
    Re-save all attendees and groups in the database. this is useful to re-run all validation code
    and allow re-calculation of automatically calculated values.  This is sometimes needed when
    doing database changes and we need to re-save everything.

    SAFETY: This -should- be safe to run at any time, but, for safety sake, recommend turning off
    any running sideboard servers before running this command.
    """
    Session.initialize_db(modify_tables=True)
    with Session() as session:
        print("Re-saving all attendees....")
        [a.presave_adjustments() for a in session.query(Attendee).all()]
        print("Re-saving all groups....")
        [g.presave_adjustments() for g in session.query(Group).all()]
        print("Saving resulting changes to database (can take a few minutes)...")
    print("Done!")


@entry_point
def resave_all_staffers():
    """
    Re-save all staffers in the database, and re-assign all

    SAFETY: This -should- be safe to run at any time, but, for safety sake, recommend turning off
    any running sideboard servers before running this command.
    """
    Session.initialize_db(modify_tables=True)
    with Session() as session:
        staffers = session.query(Attendee).filter_by(badge_type=c.STAFF_BADGE).all()

        first_staff_badge_num = c.BADGE_RANGES[c.STAFF_BADGE][0]
        last_staff_badge_num = c.BADGE_RANGES[c.STAFF_BADGE][1]
        assert len(staffers) < last_staff_badge_num - first_staff_badge_num + 1, 'not enough free staff badges, please increase limit'

        badge_num = first_staff_badge_num

        print("Re-saving all staffers....")
        for a in staffers:
            a.presave_adjustments()
            a.badge_num = badge_num
            badge_num += 1
            assert badge_num <= last_staff_badge_num
        print("Saving resulting changes to database (can take a few minutes)...")
    print("Done!")


@entry_point
def insert_admin():
    Session.initialize_db(modify_tables=True)
    with Session() as session:
        if session.insert_test_admin_account():
            print("Test admin account created successfully")
        else:
            print("Not allowed to create admin account at this time")


@entry_point
def reset_uber_db():
    assert c.DEV_BOX, 'reset_uber_db is only available on development boxes'
    Session.initialize_db(drop=True, modify_tables=True)
    insert_admin()
