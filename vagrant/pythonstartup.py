import os
import sys
import atexit
import readline
import rlcompleter
from pprint import pprint

readline.parse_and_bind('tab: complete')

history_path = os.path.expanduser('~/.pyhistory')

@atexit.register
def save_history():
    readline.write_history_file(history_path)

if os.path.exists(history_path):
    readline.read_history_file(history_path)

try:
    import sideboard
    from uber.common import *
except:
    pass
