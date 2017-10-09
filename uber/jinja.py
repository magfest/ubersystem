from uber.common import *
import traceback
import weakref
from jinja2.loaders import split_template_path
from jinja2.utils import open_if_exists
from jinja2.exceptions import TemplateNotFound


class MultiPathEnvironment(jinja2.Environment):

    def _find_requesting_templates(self):
        """
        Returns the set of all files in the call stack ending in ".html".
        """
        stack = map(lambda s: s[0], traceback.extract_stack())
        return set(filter(lambda s: s.endswith('.html'), stack))

    def _load_template(self, name, globals):
        """
        Overridden to take into consideration the templates in the call stack.
        """
        if self.loader is None:
            raise TypeError('no loader for this environment specified')

        requesting_templates = self._find_requesting_templates()

        cache_key = (weakref.ref(self.loader), name, ','.join(sorted(requesting_templates)))
        if self.cache is not None:
            template = self.cache.get(cache_key)
            if template is not None and (not self.auto_reload or
                                         template.is_up_to_date):
                return template
        template = self.loader.load(self, name, globals, requesting_templates)
        if self.cache is not None:
            self.cache[cache_key] = template
        return template


class MultiPathLoader(jinja2.FileSystemLoader):

    def get_source(self, environment, template, requesting_templates=set()):
        """
        Overridden to accept the requesting_templates parameter: a set of every
        template that has already been loaded during the current request.
        """
        pieces = split_template_path(template)
        for searchpath in self.searchpath:
            filename = os.path.join(searchpath, *pieces)
            if filename in requesting_templates:
                # If the file is already in the call stack, ignore it
                continue

            f = open_if_exists(filename)
            if f is None:
                continue
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
        raise TemplateNotFound(template)

    def load(self, environment, name, globals=None, requesting_templates=set()):
        """
        Overridden to accept the requesting_templates parameter, a set of every
        template that has already been loaded during the current request.
        """
        code = None
        if globals is None:
            globals = {}

        # first we try to get the source for this template together
        # with the filename and the uptodate function.
        source, filename, uptodate = self.get_source(environment, name, requesting_templates)

        # try to load the code from the bytecode cache if there is a
        # bytecode cache configured.
        bcc = environment.bytecode_cache
        if bcc is not None:
            bucket = bcc.get_bucket(environment, name, filename, source)
            code = bucket.code

        # if we don't have code so far (not cached, no longer up to
        # date) etc. we compile the template
        if code is None:
            code = environment.compile(source, name, filename)

        # if the bytecode cache is available and the bucket doesn't
        # have a code so far, we give the bucket the new code and put
        # it back to the bytecode cache.
        if bcc is not None and bucket.code is None:
            bucket.code = code
            bcc.set_bucket(bucket)

        return environment.template_class.from_code(environment, code,
                                                    globals, uptodate)


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
