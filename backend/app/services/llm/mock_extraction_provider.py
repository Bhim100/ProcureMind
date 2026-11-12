"""Deterministic mock extraction provider for Phase 8 automated testing.

Ensures zero live network calls during testing (AGENTS.md Rule 6).
"""

from typing import Any

from pydantic import BaseModel

from app.services.llm.extraction_interface import (
    ExtractionProviderError,
    StructuredExtractionProviderInterface,
)


class MockExtractionProvider(StructuredExtractionProviderInterface):
    """Deterministic, testable extraction provider for test suites and offline verification."""

    def __init__(
        self,
        response_sequence: list[dict[str, Any] | Exception] | None = None,
        default_response: dict[str, Any] | None = None,
        simulate_error: str | None = None,
    ) -> None:
        self.response_sequence: list[dict[str, Any] | Exception] = list(response_sequence or [])
        self.default_response = default_response
        self.simulate_error = simulate_error
        self.call_history: list[dict[str, Any]] = []

    async def extract_structured(
        self,
        prompt: str,
        response_schema: type[BaseModel],
        timeout_seconds: int = 15,
    ) -> dict[str, Any]:
        """Return configured response or raise simulated error."""
        self.call_history.append(
            {
                "prompt": prompt,
                "response_schema": response_schema,
                "timeout_seconds": timeout_seconds,
            }
        )

        if self.simulate_error == "timeout":
            raise ExtractionProviderError("Extraction provider timed out", status_code=504)
        elif self.simulate_error == "http_error":
            raise ExtractionProviderError(
                "Extraction provider returned error status 502", status_code=502
            )
        elif self.simulate_error == "unconfigured":
            raise ExtractionProviderError(
                "Structured extraction provider is unconfigured", status_code=503
            )
        elif self.simulate_error == "malformed_json":
            raise ExtractionProviderError("Malformed JSON response from extraction provider")

        if self.response_sequence:
            item = self.response_sequence.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

        if self.default_response is not None:
            return self.default_response

        # Default fallback minimal empty extraction response
        return {}

