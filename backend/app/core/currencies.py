"""
Currency standards and validation for ProcureMind.

ProcureMind strictly mandates ISO-4217 3-letter currency codes.
Binary floats are never used for monetary amounts.
"""

# Recognized major ISO-4217 3-letter currency codes commonly used in global trade and payments
SUPPORTED_CURRENCY_CODES: set[str] = {
    "USD",  # US Dollar
    "EUR",  # Euro
    "GBP",  # British Pound Sterling
    "INR",  # Indian Rupee
    "CAD",  # Canadian Dollar
    "AUD",  # Australian Dollar
    "JPY",  # Japanese Yen
    "SGD",  # Singapore Dollar
    "CHF",  # Swiss Franc
    "CNY",  # Chinese Yuan
    "HKD",  # Hong Kong Dollar
    "AED",  # UAE Dirham
    "NZD",  # New Zealand Dollar
    "SEK",  # Swedish Krona
    "NOK",  # Norwegian Krone
    "MXN",  # Mexican Peso
    "BRL",  # Brazilian Real
    "ZAR",  # South African Rand
}


def validate_currency_code(code: str) -> str:
    """
    Validates that a currency code is a valid uppercase 3-letter ISO-4217 currency.

    Raises:
        ValueError: If code is not an uppercase 3-letter string or not in the recognized currency set.
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
