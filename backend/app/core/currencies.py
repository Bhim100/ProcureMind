"""
Currency standards, scale registry, and precision validation for ProcureMind.

ProcureMind strictly mandates ISO-4217 3-letter currency codes and exact Decimal
arithmetic with currency-aware minor unit scale enforcement.
Binary floats are never used for monetary amounts.
"""

from decimal import ROUND_DOWN, Decimal

# Currency minor unit scale registry mapping ISO-4217 code to allowed fractional digits
CURRENCY_SCALES: dict[str, int] = {
    # 0 decimal currencies (zero minor units)
    "JPY": 0,  # Japanese Yen
    "KRW": 0,  # South Korean Won
    "VND": 0,  # Vietnamese Dong
    "CLP": 0,  # Chilean Peso
    # 2 decimal currencies (standard minor units)
    "USD": 2,  # US Dollar
    "EUR": 2,  # Euro
    "GBP": 2,  # British Pound Sterling
    "INR": 2,  # Indian Rupee
    "CAD": 2,  # Canadian Dollar
    "AUD": 2,  # Australian Dollar
    "SGD": 2,  # Singapore Dollar
    "CHF": 2,  # Swiss Franc
    "CNY": 2,  # Chinese Yuan
    "HKD": 2,  # Hong Kong Dollar
    "AED": 2,  # UAE Dirham
    "NZD": 2,  # New Zealand Dollar
    "SEK": 2,  # Swedish Krona
    "NOK": 2,  # Norwegian Krone
    "MXN": 2,  # Mexican Peso
    "BRL": 2,  # Brazilian Real
    "ZAR": 2,  # South African Rand
    # 3 decimal currencies (three minor units)
    "KWD": 3,  # Kuwaiti Dinar
    "BHD": 3,  # Bahraini Dinar
    "OMR": 3,  # Omani Rial
    "JOD": 3,  # Jordanian Dinar
    "TND": 3,  # Tunisian Dinar
}

SUPPORTED_CURRENCY_CODES: set[str] = set(CURRENCY_SCALES.keys())


def validate_currency_code(code: str) -> str:
    """
    Validates that a currency code is a valid uppercase 3-letter ISO-4217 currency.

    Rejects unsupported currency codes immediately. Never defaults to scale 2.
    """
    if not isinstance(code, str):
        raise TypeError("Currency code must be a string")

    clean_code = code.strip().upper()
    if len(clean_code) != 3 or not clean_code.isalpha():
        raise ValueError(f"Currency code '{code}' must be a 3-letter alphabetic ISO-4217 code")

    if clean_code not in SUPPORTED_CURRENCY_CODES:
        raise ValueError(
            f"Unsupported currency code '{clean_code}'. Must be one of: {', '.join(sorted(SUPPORTED_CURRENCY_CODES))}"
        )
    return clean_code


def get_currency_scale(currency: str) -> int:
    """
    Returns the maximum minor unit scale (number of fractional decimal places)
    for a supported ISO-4217 currency code.

    Raises:
        ValueError: If currency code is not in SUPPORTED_CURRENCY_CODES.
    """
    clean = validate_currency_code(currency)
    return CURRENCY_SCALES[clean]


def validate_currency_scale(amount: Decimal | float | str, currency: str) -> Decimal:
    """
    Validates that a Decimal monetary amount does not exceed the scale permitted
    for its currency (e.g. max 0 decimals for JPY, 2 for USD, 3 for KWD).

    Preserves exact Decimal precision without any rounding.

    Raises:
        ValueError: If amount has significant fractional precision beyond the currency's scale.
    """
    if not isinstance(amount, Decimal):
        amount = Decimal(str(amount))
    scale = get_currency_scale(currency)
    quantum = Decimal(1) if scale == 0 else Decimal(f"1e-{scale}")
    if amount != amount.quantize(quantum, rounding=ROUND_DOWN):
        raise ValueError(
            f"Monetary amount {amount} exceeds maximum allowed precision of {scale} decimal places for currency {currency}"
        )
    return amount


validate_currency_amount = validate_currency_scale
