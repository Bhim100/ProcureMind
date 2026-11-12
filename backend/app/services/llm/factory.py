"""
Factory for instantiating the active LLM investigation provider.
"""

import logging

from app.core.config import settings
from app.services.llm.extraction_interface import StructuredExtractionProviderInterface
from app.services.llm.gemini_extraction_provider import GeminiExtractionProvider
from app.services.llm.gemini_provider import GeminiLLMProvider
from app.services.llm.interface import LLMProviderInterface
from app.services.llm.mock_extraction_provider import MockExtractionProvider
from app.services.llm.mock_provider import MockLLMProvider
from app.services.llm.openai_provider import OpenAILLMProvider

logger = logging.getLogger(__name__)


def get_llm_provider() -> LLMProviderInterface | None:
    """
    Returns the configured LLM provider instance based on environment settings.
    Returns None if no API key is configured (or provider is unavailable),
    signaling the caller to return a safe unavailable fallback response.
    """
    provider_name = (settings.LLM_PROVIDER or "gemini").lower()

    if provider_name == "mock":
        return MockLLMProvider()

    if not settings.LLM_API_KEY:
        logger.info(
            "No LLM_API_KEY configured; AI explanation service is operating in unavailable fallback mode."
        )
        return None

    if provider_name == "gemini":
        return GeminiLLMProvider(
            api_key=settings.LLM_API_KEY,
            model=settings.LLM_MODEL or "gemini-3.8-flash",
        )

    if provider_name == "openai":
        return OpenAILLMProvider(
            api_key=settings.LLM_API_KEY,
            base_url=settings.LLM_BASE_URL,
            model=settings.LLM_MODEL or "gpt-4o-mini",
        )

    logger.warning(
        "Unrecognized LLM_PROVIDER '%s'; falling back to unavailable mode.", provider_name
    )
    return None


def get_extraction_provider() -> StructuredExtractionProviderInterface:
    """Returns the configured structured extraction provider based on environment settings.

    Returns GeminiExtractionProvider or MockExtractionProvider.
    """
    provider_name = (settings.LLM_PROVIDER or "gemini").lower()

    if provider_name == "mock":
        return MockExtractionProvider()

    # Default to GeminiExtractionProvider. If api_key is missing,
    # extract_structured raises ExtractionProviderError with status_code=503.
    return GeminiExtractionProvider(
        api_key=settings.LLM_API_KEY,
        model=settings.LLM_MODEL or "gemini-3.8-flash",
        base_url=settings.LLM_BASE_URL,
    )
