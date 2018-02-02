from decimal import Decimal

import pytest

from uber.common import *


@pytest.mark.parametrize('test_input,expected', [
    (Decimal(), '0.0'),
    (Decimal(0), '0.0'),
    (Decimal(0.1), '0.1'),
    ([Decimal(0), Decimal(0.1)], '[0.0, 0.1]'),
    ({'d': Decimal(0.1)}, '{"d": 0.1}')
])
def test_decimal(test_input, expected):
    assert expected == json.dumps(test_input, cls=serializer)
