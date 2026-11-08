"""
Common Pydantic types, validators, and base configuration for ProcureMind schemas.
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


def validate_money_amount(value: Decimal) -> Decimal:
    """
    Validates that a monetary amount has at most 4 decimal places (supporting up to 4 fractional digits).
    Rejects binary floating-point imprecision.
    """
    if not isinstance(value, Decimal):
        try:
            value = Decimal(str(value))
        except Exception as exc:
            raise ValueError(f"Invalid monetary value: {value}") from exc

    # Check precision: exponent cannot be lower than -4 (e.g. 10.00001 is invalid)
    exp = value.as_tuple().exponent
    if not isinstance(exp, int) or exp < -4:
        raise ValueError(f"Monetary amount {value} exceeds maximum 4-decimal precision")
    return value


def ensure_utc_datetime(dt: datetime) -> datetime:
    """Ensures datetime is timezone-aware and converted to UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


# Reusable annotated types
CurrencyCode = Annotated[
    str, Field(min_length=3, max_length=3, description="ISO-4217 3-letter currency code")
]
MoneyAmount = Annotated[
    Decimal,
    Field(ge=Decimal("0.00"), description="Fixed precision monetary amount (up to 4 decimals)"),
]


class ProcureMindBaseSchema(BaseModel):
    """Base schema for all Pydantic models with ORM mode enabled."""

    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
        extra="forbid",
    )
