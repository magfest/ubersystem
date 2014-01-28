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
    
    print()
    for model in classes:
        print(connection.creation.sql_create_model(model, Style(), classes)[0][0])

'''
createuser --superuser --pwprompt m13
createdb --owner=m13 m13
Account.objects.create(name='Eli Courtwright', email='eli@courtwright.org', access=','.join(str(level) for level,name in ACCESS_OPTS), hashed='$2a$12$RznxTw/KKp3UkGNJy0cas.hUbM4Dai3sokxo/QeAvS42QqLN56tW6')
'''
