from uber.common import *

@entry_point
def add_age_groups():
    with Session() as session:
        age_group = AgeGroup(
            desc           = 'age unknown',
            min_age        = 0,
            max_age        = 0,
            discount       = 0,
            can_register   = False
        )
        session.add(age_group)
    
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
            discount       = 10,
            can_register   = True
        )
        session.add(age_group)