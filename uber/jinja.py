from uber.common import *


class JinjaEnv:
    _env = None
    _exportable_functions = {}
    _filter_functions = {}
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
        env = jinja2.Environment(
            autoescape=True,
            loader=jinja2.FileSystemLoader(cls._template_dirs))

        for name, func in cls._exportable_functions.items():
            env.globals[name] = func

        for name, func in cls._filter_functions.items():
            env.filters[name] = func

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



def template_overrides(dirname):
    """
    Each event can have its own plugin and override our default templates with
    its own by calling this method and passing its templates directory.
    """
    JinjaEnv.insert_template_dir(dirname)

for _directory in c.TEMPLATE_DIRS:
    template_overrides(_directory)
