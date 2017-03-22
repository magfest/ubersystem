import pytest

from uber.common import *


def collect_template_paths(file_path):
    current_path = os.path.abspath(os.path.expanduser(file_path))
    while current_path != '/':
        templates_root = os.path.join(current_path, 'templates')
        if os.path.exists(templates_root):
            return glob(os.path.join(templates_root, '*.html')) + \
                   glob(os.path.join(templates_root, '**', '*.html'))
        current_path = os.path.normpath(os.path.join(current_path, '..'))
    return []


@pytest.mark.parametrize("template_path", collect_template_paths(__file__))
def test_is_valid_jinja_template(template_path):
    env = JinjaEnv.env()
    with open(template_path) as t:
        env.parse(t.read())
