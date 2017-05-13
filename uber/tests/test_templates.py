import pytest

from uber.common import *
from uber.tests import collect_template_paths, is_valid_jinja_template


@pytest.mark.parametrize("template_path", collect_template_paths(__file__))
def test_is_valid_jinja_template(template_path):
    is_valid_jinja_template(template_path)


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


def test_render_empty():
    env = JinjaEnv.env()
    cur_dir = os.path.dirname(__file__)
    env.loader.searchpath.append(cur_dir)
    try:
        template = env.get_template('autoescape_template.html')
    finally:
        if cur_dir in env.loader.searchpath:
            env.loader.searchpath.remove(cur_dir)

    result = str(open(template.filename, 'r').read())
    expected = '''\
<!DOCTYPE HTML>
<html>
<body>
{{ unsafe_string }}
{% autoescape false %}{{ safe_string }}{% endautoescape %}
</body>
</html>
'''

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
