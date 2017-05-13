from decimal import Decimal

from uber._version import __version__
from uber.common import *

from sideboard import lib


# NOTE: this will decrease the precision of some serialized decimal.Decimals
lib.serializer.register(Decimal, lambda n: float(n))
