import textwrap

import pytest
from jinja2.exceptions import TemplateNotFound

from uber.common import *
from uber.tests.conftest import *
from uber.jinja import AbsolutePathLoader, MultiPathEnvironment


__here__ = os.path.abspath(os.path.dirname(__file__))


@pytest.fixture()
def loader():
    templates = os.path.join(__here__, 'templates')
    searchpath = [
        os.path.join(templates, 'templates_{}'.format(i)) for i in (3, 2, 1)]
    return AbsolutePathLoader(searchpath)


@pytest.fixture()
def environment(loader):
    return MultiPathEnvironment(loader=loader)


class TestAbsolutePathLoader(object):

    @pytest.mark.parametrize('name,relative_path', [
        ('test_extends_1.html', 'templates/templates_3'),
        ('test_import_macros.html', 'templates/templates_1'),
        ('test_include_1.html', 'templates/templates_1'),
        ('test_standalone_1.html', 'templates/templates_1'),
        ('test_extends_2.html', 'templates/templates_3'),
        ('test_include_2.html', 'templates/templates_2'),
        ('test_standalone_2.html', 'templates/templates_2'),
        ('test_include_3.html', 'templates/templates_3'),
        ('test_standalone_3.html', 'templates/templates_3'),
    ])
    def test_get_source_relative(self, loader, name, relative_path):
        abs_path = os.path.join(__here__, relative_path, name)
        environment = jinja2.Environment(loader=loader)
        _, template, _ = loader.get_source(environment, name)
        assert abs_path == template

    @pytest.mark.parametrize('name,relative_path', [
        ('test_extends_1.html', 'templates/templates_1'),
        ('test_import_macros.html', 'templates/templates_1'),
        ('test_include_1.html', 'templates/templates_1'),
        ('test_standalone_1.html', 'templates/templates_1'),
        ('test_extends_1.html', 'templates/templates_2'),
        ('test_extends_2.html', 'templates/templates_2'),
        ('test_include_2.html', 'templates/templates_2'),
        ('test_standalone_2.html', 'templates/templates_2'),
        ('test_extends_1.html', 'templates/templates_3'),
        ('test_extends_2.html', 'templates/templates_3'),
        ('test_include_3.html', 'templates/templates_3'),
        ('test_standalone_3.html', 'templates/templates_3'),
    ])
    def test_get_source_absolute(self, loader, name, relative_path):
        abs_path = os.path.join(__here__, relative_path, name)
        environment = jinja2.Environment(loader=loader)
        _, template, _ = loader.get_source(environment, abs_path)
        assert abs_path == template

    @pytest.mark.parametrize('name,relative_path', [
        ('should_never_be_loaded.html', 'templates/not_on_searchpath'),
        ('does_not_exist.html', 'templates/templates_1'),
    ])
    def test_invalid(self, loader, name, relative_path):
        abs_path = os.path.join(__here__, relative_path, name)
        environment = jinja2.Environment(loader=loader)
        pytest.raises(TemplateNotFound, loader.get_source, environment, name)
        pytest.raises(TemplateNotFound, loader.get_source, environment, abs_path)


class TestMultiPathEnvironment(object):

    @pytest.mark.parametrize('name,relative_paths', [
        ('test_extends_1.html', ('templates/templates_3', 'templates/templates_2', 'templates/templates_1',)),
        ('test_import_macros.html', ('templates/templates_1',)),
        ('test_include_1.html', ('templates/templates_1',)),
        ('test_standalone_1.html', ('templates/templates_1',)),
        ('test_extends_2.html', ('templates/templates_3', 'templates/templates_2',)),
        ('test_include_2.html', ('templates/templates_2',)),
        ('test_standalone_2.html', ('templates/templates_2',)),
        ('test_include_3.html', ('templates/templates_3',)),
        ('test_standalone_3.html', ('templates/templates_3',)),
    ])
    def test_get_template_repeatedly(self, environment, name, relative_paths):
        for relative_path in relative_paths:
            abs_path = os.path.join(__here__, relative_path, name)
            template = environment.get_template(name)
            assert abs_path == template.filename

    @pytest.mark.parametrize('name,content', [
        ('test_extends_1.html', textwrap.dedent("""\
            templates_1.test_extends_1.header
            templates_2.test_extends_1.header
            templates_1.test_extends_1.header
            templates_3.test_extends_1.header
            templates_1.test_extends_1.header
            templates_2.test_extends_1.header
            templates_1.test_extends_1.header
            templates_1.test_extends_1.main
            templates_2.test_extends_1.main
            templates_1.test_extends_1.main
            templates_3.test_extends_1.main
            templates_1.test_extends_1.main
            templates_2.test_extends_1.main
            templates_1.test_extends_1.main
            templates_1.test_extends_1.footer
            templates_2.test_extends_1.footer
            templates_1.test_extends_1.footer
            templates_3.test_extends_1.footer
            templates_1.test_extends_1.footer
            templates_2.test_extends_1.footer
            templates_1.test_extends_1.footer""")),
        ('test_import_macros.html', '\n'),
        ('test_include_1.html', 'test_include_1'),
        ('test_standalone_1.html', 'templates_1.test_standalone_1'),
        ('test_extends_2.html', textwrap.dedent("""\
            templates_2.test_extends_2
            templates_3.test_extends_2""")),
        ('test_include_2.html', textwrap.dedent("""\
            test_include_2
            test_include_1""")),
        ('test_standalone_2.html', 'templates_2.test_standalone_2'),
        ('test_include_3.html', textwrap.dedent("""\
            test_include_3
            test_include_2
            test_include_1""")),
        ('test_standalone_3.html', textwrap.dedent("""\
            templates_3.test_standalone_3
            test_include_3
            test_include_2
            test_include_1""")),
    ])
    def test_render_template(self, environment, name, content):
        template = environment.get_template(name)
        rendered_content = template.render()
        assert content == rendered_content

    @pytest.mark.parametrize('name,relative_path', [
        ('should_never_be_loaded.html', 'templates/not_on_searchpath'),
        ('does_not_exist.html', 'templates/templates_1'),
    ])
    def test_invalid(self, environment, name, relative_path):
        abs_path = os.path.join(__here__, relative_path, name)
        pytest.raises(TemplateNotFound, environment.get_template, name)
        pytest.raises(TemplateNotFound, environment.get_template, abs_path)
