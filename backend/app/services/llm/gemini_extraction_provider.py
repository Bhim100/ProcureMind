"""Google Gemini provider implementation for structured document extraction."""

import asyncio
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

        candidate_models = [self.model]
        for fallback in ["gemini-3.1-flash-lite", "gemini-3.8-flash"]:
            if fallback not in candidate_models:
                candidate_models.append(fallback)

        last_error_status = 502
        response = None

        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            for model_to_use in candidate_models:
                endpoint_url = (
                    f"{self.base_url}/models/{model_to_use}:generateContent?key={self.api_key}"
                )
                try:
                    response = await client.post(
                        endpoint_url,
                        json=request_body,
                        headers={"Content-Type": "application/json"},
                    )
                except httpx.TimeoutException:
                    logger.warning(f"Gemini model {model_to_use} timed out; checking fallback")
                    continue
                except httpx.RequestError as exc:
                    logger.warning(
                        f"Gemini model {model_to_use} network error: {type(exc).__name__}"
                    )
                    continue

                if response.status_code == 200:
                    break
                elif response.status_code in (503, 429):
                    logger.warning(
                        f"Gemini model {model_to_use} returned {response.status_code} (overloaded/rate-limited). Trying fallback model."
                    )
                    last_error_status = response.status_code
                    await asyncio.sleep(0.5)
                else:
                    logger.error(f"Gemini API returned HTTP {response.status_code}")
                    last_error_status = response.status_code
                    break

        if response is None or response.status_code != 200:
            logger.error(f"All Gemini extraction attempts failed (last status {last_error_status})")
            raise ExtractionProviderError(
                f"Extraction provider returned error status {last_error_status}",
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
