import pytest

from uber.common import *


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
    template_dirs = c.TEMPLATE_DIRS
    if not template_dirs:
        template_dirs = guess_template_dirs(file_path)

    template_paths = []
    for template_dir in template_dirs:
        template_paths.extend(glob(os.path.join(template_dir, '*.html')))
        template_paths.extend(glob(os.path.join(template_dir, '**', '*.html')))
    return template_paths


@pytest.mark.parametrize("template_path", collect_template_paths(__file__))
def test_is_valid_jinja_template(template_path):
    env = JinjaEnv.env()
    with open(template_path) as t:
        env.parse(t.read())


def test_verify_jinja_autoescape_template():
    env = JinjaEnv.env()
    cur_dir = os.path.dirname(__file__)
    env.loader.searchpath.append(cur_dir)
    try:
        template = env.get_template('autoescape_template.html')
    finally:
        if cur_dir in env.loader.searchpath:
            env.loader.searchpath.remove(cur_dir)

    result = template.render(unsafe_string='<img src="#">', safe_string='<b>bold</b>')
    expected = '''\
<!DOCTYPE HTML>
<html>
<body>
&lt;img src=&#34;#&#34;&gt;
<b>bold</b>
</body>
</html>'''

    assert result == expected


def test_verify_jinja_autoescape_string():
    env = JinjaEnv.env()
    template = env.from_string('''\
{{ unsafe_string }}
{% autoescape false %}{{ safe_string }}{% endautoescape %}''')

    result = template.render(unsafe_string='<img src="#">', safe_string='<b>bold</b>')
    expected = '''\
&lt;img src=&#34;#&#34;&gt;
<b>bold</b>'''

    assert result == expected
