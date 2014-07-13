import os
from os.path import abspath, basename, dirname

__here__ = dirname(abspath(__file__))
collect_ignore = [basename(f) for f in os.listdir(__here__) if f.endswith('.py')]
