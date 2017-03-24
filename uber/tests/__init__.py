from uber.common import *

from mock import Mock
from unittest import TestCase

import pytest

'''
class TestPreassignedBadgeDeletion(TestBadgeChange):
    def test_delete_first(self):
        self.staff_one.delete()

    def test_delete_middle(self):
        self.staff_three.delete()

    def test_delete_end(self):
        self.staff_five.delete()
'''


def guess_template_dirs(file_path):
    if not file_path:
        return []

    current_path = os.path.abspath(os.path.expanduser(file_path))
    while current_path != '/':
        template_dir = os.path.join(current_path, 'templates')
        if os.path.exists(template_dir):
            return [template_dir]
        current_path = os.path.normpath(os.path.join(current_path, '..'))
    return []


def collect_template_paths(file_path):
    template_dirs = guess_template_dirs(file_path)
    template_paths = []
    for template_dir in template_dirs:
        for root, _, _ in os.walk(template_dir):
            for ext in ('html', 'htm', 'txt'):
                file_pattern = '*.{}'.format(ext)
                template_paths.extend(glob(os.path.join(root, file_pattern)))

    return template_paths


def is_valid_jinja_template(template_path):
    env = JinjaEnv.env()
    with open(template_path) as t:
        env.parse(t.read())
