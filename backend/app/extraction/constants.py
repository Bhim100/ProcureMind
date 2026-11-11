"""Constants, thresholds, and utility functions for deterministic document extraction."""

# Usable text threshold: A page or document is considered to have usable native text
# if it contains at least 30 non-whitespace characters and at least 10 alphanumeric characters.
USABLE_TEXT_CHAR_THRESHOLD: int = 30
USABLE_TEXT_ALPHANUMERIC_MIN: int = 10


def has_usable_text(text: str | None) -> bool:
    """Determine whether extracted text meets the threshold for usable native text.

    If not, OCR fallback should be invoked for the page.
    """
    if not text:
        return False
    non_ws_count = sum(1 for c in text if not c.isspace())
    if non_ws_count < USABLE_TEXT_CHAR_THRESHOLD:
        return False
    alnum_count = sum(1 for c in text if c.isalnum())
    return alnum_count >= USABLE_TEXT_ALPHANUMERIC_MIN


class ExtractionError(Exception):
    """Safe exception raised during document extraction.

    Message should not contain sensitive document content or PII.
    """

    def __init__(self, message: str, safe_detail: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.safe_detail = safe_detail or message
