"""Google Gemini provider implementation for structured document extraction."""

import json
import logging
from typing import Any

import httpx
from pydantic import BaseModel

from app.core.config import settings
from app.services.llm.extraction_interface import (
    ExtractionProviderError,
    StructuredExtractionProviderInterface,
)

logger = logging.getLogger(__name__)


class GeminiExtractionProvider(StructuredExtractionProviderInterface):
    """Structured extraction provider connecting to Google Gemini REST API."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self.api_key = api_key or settings.LLM_API_KEY
        self.model = model or settings.LLM_MODEL or "gemini-3.8-flash"
        self.base_url = (
            base_url or settings.LLM_BASE_URL or "https://generativelanguage.googleapis.com/v1beta"
        ).rstrip("/")

    async def extract_structured(
        self,
        prompt: str,
        response_schema: type[BaseModel],
        timeout_seconds: int = 15,
    ) -> dict[str, Any]:
        """Call Gemini generateContent with application/json output mode."""
        if not self.api_key:
            logger.warning("LLM extraction requested but LLM_API_KEY is not configured")
            raise ExtractionProviderError(
                "Structured extraction provider is unconfigured",
                status_code=503,
            )

        endpoint_url = f"{self.base_url}/models/{self.model}:generateContent?key={self.api_key}"

        request_body = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": prompt}],
                }
            ],
            "generationConfig": {
                "temperature": 0.0,
                "response_mime_type": "application/json",
            },
        }

        try:
            async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                response = await client.post(
                    endpoint_url,
                    json=request_body,
                    headers={"Content-Type": "application/json"},
                )
        except httpx.TimeoutException as exc:
            logger.error("Gemini extraction request timed out")
            raise ExtractionProviderError("Extraction provider timed out", status_code=504) from exc
        except httpx.RequestError as exc:
            logger.error(f"Gemini extraction network failure: {type(exc).__name__}")
            raise ExtractionProviderError(
                "Network failure connecting to extraction provider", status_code=502
            ) from exc

        if response.status_code != 200:
            logger.error(f"Gemini API returned HTTP {response.status_code}")
            raise ExtractionProviderError(
                f"Extraction provider returned error status {response.status_code}",
                status_code=502,
            )

        try:
            resp_data = response.json()
            candidates = resp_data.get("candidates", [])
            if not candidates:
                raise ExtractionProviderError(
                    "No response candidates returned by extraction provider"
                )

            first_candidate = candidates[0]
            content = first_candidate.get("content", {})
            parts = content.get("parts", [])
            if not parts:
                raise ExtractionProviderError("Empty content parts in provider response")

            raw_text = parts[0].get("text", "")
            return json.loads(raw_text)
        except (json.JSONDecodeError, KeyError, IndexError) as exc:
            logger.error("Failed to parse JSON response from Gemini")
            raise ExtractionProviderError(
                "Malformed JSON response from extraction provider"
            ) from exc
