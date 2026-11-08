"""
Reference and identifier normalization routines for ProcureMind.

Ensures deterministic, case-folded, whitespace-collapsed string representations
for exact matching while preserving raw provenance values.
"""


def normalize_reference_identifier(val: str | None) -> str | None:
    """
    Normalizes a reference or identifier string.

    Rules:
    - Strips leading and trailing whitespace.
    - Collapses internal consecutive whitespace runs into a single space.
    - Folds case to uppercase.
    - Returns None if the input is None or empty/whitespace only.

    Examples:
        " INV-2026-001 " -> "INV-2026-001"
        "inv  2026   001" -> "INV 2026 001"
        None -> None
        "   " -> None
    """
    if val is None:
        return None
    cleaned = " ".join(val.strip().split())
    if not cleaned:
        return None
    return cleaned.upper()
