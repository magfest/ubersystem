"""The read-only Ranking display skips a saved choice that is no longer
offered instead of raising.
"""

import re

from markupsafe import Markup

from uber.config import c
from uber.forms.widgets import Ranking
from uber.jinja import JinjaEnv

KNOWN = 'aaaaaaaa-0000-0000-0000-000000000001'
GONE = 'dcc25b3f-d352-4c4f-9a92-49b15742d3a5'


class _Form:
    read_only = True


class _Field:
    """The bits of a WTForms field the macro's read-only Ranking branch reads."""
    def __init__(self, data, choices):
        self.data = data
        self.choices = choices
        self.form = _Form()
        self.widget = Ranking()
        self.name = self.id = 'room_type_preference'
        self.label = Markup('<label>Room Types</label>')
        self.description = ''
        self.flags = type('F', (), {'required': False})()
        self.render_kw = {}
        self.type = 'SelectMultipleField'

    def __call__(self, **kw):
        return Markup('')


class _App:
    qualifies_for_staff_lottery = False


def _render(field):
    tpl = JinjaEnv.env().from_string(
        "{% import 'forms/macros.html' as form_macros with context %}"
        "{{ form_macros.input(field) }}")
    html = tpl.render(c=c, field=field, application=_App(), admin_area=False)
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', html))


def test_unknown_saved_choice_is_skipped_not_fatal():
    field = _Field([GONE, KNOWN], [(KNOWN, {'name': 'Single King - Standard'})])

    text = _render(field)

    assert '1) Single King - Standard' in text
    assert GONE not in text


def test_every_choice_gone_renders_empty_list():
    field = _Field([GONE], [])
    _render(field)  # must not raise
