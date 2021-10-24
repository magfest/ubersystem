import os
from decimal import Decimal

from pockets.autolog import log

from uber._version import __version__  # noqa: F401


def on_load():
    """
    Called by sideboard when the uber plugin is loaded.
    """
    # Note: The following imports have side effects
    from uber import config  # noqa: F401
    from uber import api  # noqa: F401
    from uber import automated_emails  # noqa: F401
    from uber import custom_tags  # noqa: F401
    from uber import jinja  # noqa: F401
    from uber import menu  # noqa: F401
    from uber import models  # noqa: F401
    from uber import model_checks  # noqa: F401
    from uber import sep_commands  # noqa: F401
    from uber import server  # noqa: F401
    from uber import tasks  # noqa: F401


# sideboard must be imported AFTER the on_load() function is declared,
# otherwise on_load() won't exist yet when sideboard looks for it.
import sideboard  # noqa: E402


# NOTE: this will decrease the precision of some serialized decimal.Decimals
sideboard.lib.serializer.register(Decimal, lambda n: float(n))

