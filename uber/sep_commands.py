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
