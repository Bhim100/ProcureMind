"""
OpenAI-compatible REST provider for Phase 6 investigation using httpx.
"""

import json
import logging
import uuid
from typing import Any

import httpx

from app.core.config import settings
from app.schemas.investigation import LLMInvestigationOutput
from app.services.llm.gemini_provider import SYSTEM_PROMPT
from app.services.llm.interface import LLMProviderInterface

logger = logging.getLogger(__name__)


class OpenAILLMProvider(LLMProviderInterface):
    """Integrates with OpenAI or OpenAI-compatible endpoints via REST."""

    provider_name = "openai"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
    ):
        self.api_key = api_key or settings.LLM_API_KEY
        self.base_url = (base_url or settings.LLM_BASE_URL or "https://api.openai.com/v1").rstrip(
            "/"
        )
        self.model = model or settings.LLM_MODEL or "gpt-4o-mini"
        self.timeout = settings.LLM_TIMEOUT_SECONDS

    async def investigate(
        self,
        question: str,
        context: dict[str, Any],
        discrepancy_id: uuid.UUID | None = None,
    ) -> LLMInvestigationOutput:
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY is not configured")

        url = f"{self.base_url}/chat/completions"

        prompt_payload = {
            "question": question,
            "focused_discrepancy_id": str(discrepancy_id) if discrepancy_id else None,
            "transaction_context": context,
        }

        user_content = json.dumps(prompt_payload, indent=2, default=str)

        request_body = {
            "model": self.model,
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(url, headers=headers, json=request_body)
            resp.raise_for_status()
            data = resp.json()

        choices = data.get("choices", [])
        if not choices:
            raise ValueError("OpenAI returned empty choices")

        text_content = choices[0].get("message", {}).get("content", "")
        if not text_content:
            raise ValueError("OpenAI response missing message content")

        return LLMInvestigationOutput.model_validate_json(text_content)
