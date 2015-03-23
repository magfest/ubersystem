from uber.common import *

@entry_point
def add_age_groups():
    with Session() as session:
        age_group = AgeGroup(
            desc           = 'n/a',
            min_age        = 0,
            max_age        = 999,
            discount       = 0,
            can_register   = True
        )
        session.add(age_group)

@entry_point
def upgrade_db():
    connection = Session.engine.connect()
    trans = connection.begin()
    try:
        sql_update = '''ALTER TABLE Job ADD COLUMN type INTEGER NOT NULL DEFAULT 252034462; ALTER TABLE Job ALTER COLUMN weight SET DEFAULT 1; ALTER TABLE food_restrictions ADD COLUMN sandwich_pref INTEGER NOT NULL DEFAULT 127073423; ALTER TABLE food_restrictions ADD COLUMN no_cheese BOOLEAN NOT NULL DEFAULT FALSE; DROP TABLE room CASCADE; DROP TABLE checkout;'''
        result = connection.execute(sql_update)
        trans.commit()
    except:
        trans.rollback()
        raise
