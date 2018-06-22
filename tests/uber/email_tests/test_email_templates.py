import os
from collections import OrderedDict

import pytest

from uber.automated_emails import AutomatedEmailFixture
from uber.jinja import JinjaEnv
from uber.models import Attendee, AutomatedEmail, Session


__here__ = os.path.dirname(os.path.abspath(__file__))


@pytest.mark.parametrize('plugins,expected', [
    (['plugin_1'], 'Hello plugin_1!'),
    (['plugin_1', 'plugin_2'], 'Hey plugin_2!'),
    (['plugin_1', 'plugin_2', 'plugin_3'], 'Hey plugin_3!'),
])
def test_email_templates(plugins, expected, monkeypatch):
    monkeypatch.setattr(JinjaEnv, '_env', None)
    monkeypatch.setattr(JinjaEnv, '_exportable_functions', {})
    monkeypatch.setattr(JinjaEnv, '_filter_functions', {})
    monkeypatch.setattr(JinjaEnv, '_test_functions', {})
    monkeypatch.setattr(JinjaEnv, '_template_dirs', [])
    monkeypatch.setattr(AutomatedEmail, '_fixtures', OrderedDict())

    for plugin in plugins:
        JinjaEnv.insert_template_dir(os.path.join(__here__, plugin, 'templates'))

    with Session() as session:
        for email in session.query(AutomatedEmail).all():
            session.delete(email)

    for i in range(1, 4):
        AutomatedEmailFixture(
            Attendee,
            'Test Template {}'.format(i),
            'test_template.txt',
            lambda a: True,
            needs_approval=False,
            ident='test_template_{}'.format(i))

    AutomatedEmail.reconcile_fixtures()

    with Session() as session:
        attendee = Attendee(first_name='Test', last_name='Email', email='test@example.com')
        for i in range(1, 4):
            automated_email = session.query(AutomatedEmail).filter_by(ident='test_template_{}'.format(i)).one()
            for i in range(1, 4):
                assert expected == automated_email.render_body(attendee).strip(), 'render() call {}'.format(i)
