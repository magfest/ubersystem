from decimal import Decimal

from sideboard import lib

# NOTE: The following imports have side effects
from uber._version import __version__  # noqa: F401
from uber.config import c  # noqa: F401
from uber import api  # noqa: F401
from uber import automated_emails  # noqa: F401
from uber import automated_emails_server  # noqa: F401
from uber import custom_tags  # noqa: F401
from uber import jinja  # noqa: F401
from uber import menu  # noqa: F401
from uber import models  # noqa: F401
from uber import model_checks  # noqa: F401
from uber import notifications  # noqa: F401
from uber import sep_commands  # noqa: F401
from uber import server  # noqa: F401


# NOTE: this will decrease the precision of some serialized decimal.Decimals
lib.serializer.register(Decimal, lambda n: float(n))
