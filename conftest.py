"""
Root conftest.py — sets UBER_CONFIG_FILES before any uber module is imported.

pytest loads conftest.py files from the rootdir downward, so this file runs
before tests/uber/conftest.py (which imports from uber.config).  Setting the
env var here guarantees the test-defaults.ini is picked up at parse time.
"""
import os

os.environ.setdefault('UBER_CONFIG_FILES', 'test-defaults.ini')
