from uber.common import *


class JinjaEnv:
    _env = None
    _exportable_functions = {}
    _filter_functions = {}
    _template_dirs = []

    @staticmethod
    def insert_template_dir(dirname):
        """
        Add another template directory we should search when looking up templates.
        """
        JinjaEnv._template_dirs.insert(0, dirname)

    @staticmethod
    def env():
        if JinjaEnv._env is None:
            JinjaEnv._env = JinjaEnv._init_env()
        return JinjaEnv._env

    @staticmethod
    def _init_env():
        env = jinja2.Environment(
                autoescape=True,
                loader=jinja2.FileSystemLoader(JinjaEnv._template_dirs)
            )

        for name, func in JinjaEnv._exportable_functions.items():
            env.globals[name] = func

        for name, func in JinjaEnv._filter_functions.items():
            env.filters[name] = func

        return env

    @staticmethod
    def jinja_export(name=None):
        def wrap(func):
            JinjaEnv._exportable_functions[name if name else func.__name__] = func
            return func
        return wrap

    @classmethod
    def jinja_filter(cls, name=None):
        def _register(func, _name=None):
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
