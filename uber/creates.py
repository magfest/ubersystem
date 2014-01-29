from uber.common import *
from uber import models

from sys import argv

class Style:
    def __getattr__(self, name):
        return lambda text: text

with open('uber/models.py') as f:
    text = f.read()
    classes = sorted(models.all_models(), key=lambda c: text.index('class ' + c.__name__ + '('))

if __name__ == '__main__':
    if len(argv) > 1:
        classes = [c for c in classes if c.__name__ in argv[1:]]
    
    with closing(connection.cursor()) as cursor:
        for model in reversed(classes):
            sql = 'DROP TABLE IF EXISTS "{}";'.format(model.__name__)
            print(sql)
            cursor.execute(sql)

        for model in classes:
            sql = connection.creation.sql_create_model(model, Style(), classes)[0][0]
            print(sql)
            cursor.execute(sql)
    
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
