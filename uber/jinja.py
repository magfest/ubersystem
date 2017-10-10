from uber.common import *
import traceback
import weakref
from jinja2.loaders import split_template_path
from jinja2.utils import open_if_exists
from jinja2.exceptions import TemplateNotFound


class MultiPathEnvironment(jinja2.Environment):

    @request_cached_property
    def _templates_loaded_for_current_request(self):
        return set()

    def _load_template(self, name, globals):
        """
        Overridden to consider templates already loaded during the current request.
        """
        if self.loader is None:
            raise TypeError('no loader for this environment specified')

        loaded_templates = self._templates_loaded_for_current_request
        cache_key = (weakref.ref(self.loader), name, ','.join(sorted(loaded_templates)))
        if self.cache is not None:
            template = self.cache.get(cache_key)
            if template is not None and (not self.auto_reload or
                                         template.is_up_to_date):
                self._templates_loaded_for_current_request.add(template.filename)
                return template

        template = self.loader.load(self, name, globals)
        self._templates_loaded_for_current_request.add(template.filename)

        if self.cache is not None:
            self.cache[cache_key] = template
        return template


class MultiPathLoader(jinja2.FileSystemLoader):

    def _get_source_if_exists(self, filename):
        f = open_if_exists(filename)
        if f is None:
            return None
        try:
            contents = f.read().decode(self.encoding)
        finally:
            f.close()

        mtime = os.path.getmtime(filename)

        def uptodate():
            try:
                return os.path.getmtime(filename) == mtime
            except OSError:
                return False
        return contents, filename, uptodate

    def get_source(self, environment, template):
        """
        Overridden to take into account the set of templates that have already
        been loaded during the current request.
        """
        loaded_templates = environment._templates_loaded_for_current_request
        pieces = split_template_path(template)
        ignored_filename = None
        for searchpath in self.searchpath:
            filename = os.path.join(searchpath, *pieces)
            if filename in loaded_templates:
                # If the file is already in the call stack, ignore it for now
                ignored_filename = filename
                continue

            source = self._get_source_if_exists(filename)
            if source:
                return source

        if ignored_filename:
            # We actually did find the template, but we ignored it because
            # it's already been loaded at least once this request. We are
            # searching for templates that _haven't_ been loaded yet, but
            # once we've loaded all the templates with a given name, we can
            # fall back to a template we've already loaded
            source = self._get_source_if_exists(ignored_filename)
            if source:
                return source
        raise TemplateNotFound(template)


class JinjaEnv:
    _env = None
    _exportable_functions = {}
    _filter_functions = {}
    _test_functions = {}
    _template_dirs = []

    @classmethod
    def insert_template_dir(cls, dirname):
        """
        Add another template directory we should search when looking up templates.
        """
        if cls._env and cls._env.loader:
            cls._env.loader.searchpath.insert(0, dirname)
        else:
            cls._template_dirs.insert(0, dirname)

    @classmethod
    def env(cls):
        if cls._env is None:
            cls._env = cls._init_env()
        return cls._env

    @classmethod
    def _init_env(cls):
        env = MultiPathEnvironment(
            autoescape=True,
            loader=MultiPathLoader(cls._template_dirs))

        for name, func in cls._exportable_functions.items():
            env.globals[name] = func

        for name, func in cls._filter_functions.items():
            env.filters[name] = func

        for name, func in cls._test_functions.items():
            env.tests[name] = func

        return env

    @classmethod
    def jinja_export(cls, name=None):
        def _register(func, _name=None):
            if cls._env:
                cls._env.globals[_name if _name else func.__name__] = func
            else:
                cls._exportable_functions[_name if _name else func.__name__] = func

        if isinstance(name, FunctionType):
            _register(name)
            return name
        else:
            def registrar(func):
                _register(func, name)
                return func
            return registrar

    @classmethod
    def jinja_filter(cls, name=None):
        def _register(func, _name=None):
            if cls._env:
                cls._env.filters[_name if _name else func.__name__] = func
            else:
                cls._filter_functions[_name if _name else func.__name__] = func

        if isinstance(name, FunctionType):
            _register(name)
            return name
        else:
            def registrar(func):
                _register(func, name)
                return func
            return registrar

    @classmethod
    def jinja_test(cls, name=None):
        def _register(func, _name=None):
            if cls._env:
                cls._env.tests[_name if _name else func.__name__] = func
            else:
                cls._test_functions[_name if _name else func.__name__] = func

        if isinstance(name, FunctionType):
            _register(name)
            return name
        else:
            def registrar(func):
                _register(func, name)
                return func
            return registrar


def template_overrides(dirname):
    """
    Each event can have its own plugin and override our default templates with
    its own by calling this method and passing its templates directory.
    """
    JinjaEnv.insert_template_dir(dirname)

for _directory in c.TEMPLATE_DIRS:
    template_overrides(_directory)
