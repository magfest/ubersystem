from uber.common import *
from uber import models

from sys import argv

classes = models.all_models()

class Style:
    def __getattr__(self, name):
        return lambda text: text

with open('uber/models.py') as f:
    text = f.read()
    classes.sort(key = lambda c: text.index('class ' + c.__name__ + '('))

if __name__ == '__main__':
    if len(argv) > 1:
        classes = [c for c in classes if c.__name__ in argv[1:]]
    
    for model in reversed(classes):
        print('DROP TABLE IF EXISTS "{}";'.format(model.__name__))
    
    for model in classes:
        print(connection.creation.sql_create_model(model, Style(), classes)[0][0])
    
    print("""INSERT INTO "Account" (name, email, access, hashed) VALUES ('{name}', '{email}', '{access}', '{hashed}');"""
          .format(name='Dev Admin Account',
                  email='magfest@example.com',
                  access=','.join(str(level) for level, name in ACCESS_OPTS),
                  hashed=bcrypt.hashpw('magfest', bcrypt.gensalt())))
