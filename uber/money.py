from __future__ import annotations

import functools
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, overload

from sqlalchemy.types import Integer, TypeDecorator

__all__ = ["Money", "MoneyType"]

_CONSTRUCTOR_TOKEN = object()


@functools.total_ordering
class Money:
    """A type-safe, immutable representation of a monetary amount stored internally as integer cents.

    Prevents floating-point rounding errors and ambiguity between dollars and cents.
    Disallows accidental arithmetic with raw scalars (except scaling or zero checks).
    Direct instantiation via Money(...) is disallowed; use named factory methods:
      Money.from_cents(...)
      Money.from_dollars(...)
      Money.zero()
    """

    __slots__ = ("cents",)
    cents: int

    def __init__(self, token: object, cents: int) -> None:
        if token is not _CONSTRUCTOR_TOKEN:
            raise TypeError(
                "Direct instantiation via Money(...) is disallowed; "
                "use Money.from_cents(), Money.from_dollars(), or Money.zero()."
            )
        if not isinstance(cents, int) or isinstance(cents, bool):
            raise TypeError(
                f"Money cents must be an integer, got {type(cents).__name__}: {cents!r}"
            )
        object.__setattr__(self, "cents", cents)

    def __setattr__(self, key: str, value: Any) -> None:
        raise AttributeError("Money instances are immutable")

    def __delattr__(self, key: str) -> None:
        raise AttributeError("Money instances are immutable")

    @classmethod
    def from_cents(cls, cents: int | Money) -> Money:
        """Construct a Money instance from integer cents."""
        if isinstance(cents, Money):
            return cents
        if cents == 0 and not isinstance(cents, bool):
            return _ZERO
        if not isinstance(cents, int) or isinstance(cents, bool):
            raise TypeError(
                f"Money cents must be an integer, got {type(cents).__name__}: {cents!r}"
            )
        return cls(_CONSTRUCTOR_TOKEN, cents)

    @classmethod
    def from_dollars(cls, dollars: float | str | Decimal | Money) -> Money:
        """Construct a Money instance from a dollar amount, rounding to nearest cent."""
        if isinstance(dollars, Money):
            return dollars
        if isinstance(dollars, int) and not isinstance(dollars, bool):
            return cls.from_cents(dollars * 100)

        if isinstance(dollars, str):
            clean = dollars.strip().replace("$", "").replace(",", "").replace(" ", "")
            try:
                dec = Decimal(clean)
            except InvalidOperation as e:
                raise ValueError(f"Cannot parse string as money: {dollars!r}") from e
        elif isinstance(dollars, Decimal):
            dec = dollars
        elif isinstance(dollars, float):
            dec = Decimal(str(dollars))
        else:
            raise TypeError(
                f"Cannot convert {type(dollars).__name__} to Money: {dollars!r}"
            )

        cents = int((dec * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))
        return cls.from_cents(cents)

    @classmethod
    def zero(cls) -> Money:
        return _ZERO

    @property
    def dollars(self) -> Decimal:
        return (Decimal(self.cents) / Decimal(100)).quantize(Decimal("0.01"))

    @property
    def amount_str(self) -> str:
        return self.format(currency_symbol="")

    def format(
        self,
        show_abs: bool = False,
        strip_zero_cents: bool = True,
        currency_symbol: str = "$",
    ) -> str:
        """Format as currency string, e.g. '$12.34', '$12', or '-$12.34'."""
        cents = abs(self.cents) if show_abs else self.cents
        sign = "-" if cents < 0 else ""
        dollars, cents = divmod(abs(cents), 100)
        if strip_zero_cents and cents == 0:
            return f"{sign}{currency_symbol}{dollars:,}"
        return f"{sign}{currency_symbol}{dollars:,}.{cents:02d}"

    def __str__(self) -> str:
        return self.format(strip_zero_cents=True)

    def __repr__(self) -> str:
        return f"Money.from_cents({self.cents})"

    def __pos__(self) -> Money:
        return self

    def __neg__(self) -> Money:
        return self.from_cents(-self.cents)

    def __abs__(self) -> Money:
        return self.from_cents(abs(self.cents))

    def abs(self) -> Money:
        return abs(self)

    def __bool__(self) -> bool:
        return self.cents != 0

    def __hash__(self) -> int:
        return hash(self.cents)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Money):
            return self.cents == other.cents
        return self.cents == 0 if other == 0 and not isinstance(other, bool) else False

    def __lt__(self, other: Any) -> bool:
        if isinstance(other, Money):
            return self.cents < other.cents
        if other == 0 and not isinstance(other, bool):
            return self.cents < 0
        return NotImplemented

    def __add__(self, other: Any) -> Money:
        if isinstance(other, Money):
            return self.from_cents(self.cents + other.cents)
        raise TypeError(
            f"Cannot add {type(other).__name__} to Money. Use Money instances."
        )

    def __radd__(self, other: Any) -> Money:
        if other == 0 and not isinstance(other, bool):
            return self
        return self.__add__(other)

    def __sub__(self, other: Any) -> Money:
        if isinstance(other, Money):
            return self.from_cents(self.cents - other.cents)
        raise TypeError(
            f"Cannot subtract {type(other).__name__} from Money. Use Money instances."
        )

    def __rsub__(self, other: Any) -> Money:
        if other == 0 and not isinstance(other, bool):
            return -self
        raise TypeError(f"Cannot subtract Money from {type(other).__name__}.")

    def __mul__(self, other: float | Decimal) -> Money:
        if isinstance(other, int) and not isinstance(other, bool):
            return self.from_cents(self.cents * other)
        if isinstance(other, (float, Decimal)):
            dec = Decimal(str(other)) if isinstance(other, float) else other
            return self.from_cents(
                int(
                    (Decimal(self.cents) * dec).quantize(
                        Decimal(1), rounding=ROUND_HALF_UP
                    )
                )
            )
        return NotImplemented

    def __rmul__(self, other: float | Decimal) -> Money:
        return self.__mul__(other)

    @overload
    def __truediv__(self, other: Money) -> Decimal: ...

    @overload
    def __truediv__(self, other: float | Decimal) -> Money: ...

    def __truediv__(self, other: float | Decimal | Money) -> Money | Decimal:
        if isinstance(other, Money):
            if other.cents == 0:
                raise ZeroDivisionError("division by zero Money")
            return Decimal(self.cents) / Decimal(other.cents)
        if isinstance(other, int) and not isinstance(other, bool):
            if other == 0:
                raise ZeroDivisionError("division by zero")
            return self.from_cents(
                int(
                    (Decimal(self.cents) / Decimal(other)).quantize(
                        Decimal(1), rounding=ROUND_HALF_UP
                    )
                )
            )
        if isinstance(other, (float, Decimal)):
            dec = Decimal(str(other)) if isinstance(other, float) else other
            if dec == 0:
                raise ZeroDivisionError("division by zero")
            return self.from_cents(
                int(
                    (Decimal(self.cents) / dec).quantize(
                        Decimal(1), rounding=ROUND_HALF_UP
                    )
                )
            )
        return NotImplemented

    def __floordiv__(self, other: int) -> Money:
        if isinstance(other, int) and not isinstance(other, bool):
            if other == 0:
                raise ZeroDivisionError("integer division by zero")
            return self.from_cents(self.cents // other)
        return NotImplemented

    def __mod__(self, other: int) -> Money:
        if isinstance(other, int) and not isinstance(other, bool):
            return self.from_cents(self.cents % other)
        return NotImplemented

    @classmethod
    def _coerce(cls, v: Any) -> Money:
        if isinstance(v, Money):
            return v
        if isinstance(v, int) and not isinstance(v, bool):
            return cls.from_cents(v)
        if isinstance(v, (str, float, Decimal)):
            return cls.from_dollars(v)
        raise TypeError(f"Cannot parse value into Money: {v!r}")

    @classmethod
    def __get_pydantic_core_schema__(cls, source_type: Any, handler: Any) -> Any:
        try:
            from pydantic_core import core_schema

            return core_schema.no_info_plain_validator_function(
                cls._coerce,
                serialization=core_schema.plain_serializer_function_ser_schema(
                    lambda m: m.cents, return_schema=core_schema.int_schema()
                ),
            )
        except ImportError:
            return None

    @classmethod
    def __get_validators__(cls) -> Any:
        yield cls._coerce


_ZERO = Money(_CONSTRUCTOR_TOKEN, 0)


class MoneyType(TypeDecorator):
    """SQLAlchemy / SQLModel column type that persists Money as integer cents in the database."""

    impl = Integer
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> int | None:
        if value is None:
            return None
        if isinstance(value, Money):
            return value.cents
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        return Money.from_dollars(value).cents

    def process_result_value(self, value: int | None, dialect: Any) -> Money | None:
        return None if value is None else Money.from_cents(value)
