"""Abstract interface for structured document extraction LLM providers."""

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel


class ExtractionProviderError(Exception):
    """Exception raised when an extraction LLM provider call fails."""

    def __init__(self, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class StructuredExtractionProviderInterface(ABC):
    """Abstract interface defining the contract for structured document extraction providers."""

    @abstractmethod
    async def extract_structured(
        self,
        prompt: str,
        response_schema: type[BaseModel],
        timeout_seconds: int = 15,
    ) -> dict[str, Any]:
        """Execute structured extraction and return raw parsed JSON dictionary.

        Parameters:
            prompt: Formatted instruction prompt containing delimited source context.
            response_schema: Target Pydantic model class defining the expected schema.
            timeout_seconds: Maximum allowed latency in seconds.

        Returns:
            dict[str, Any]: Unvalidated JSON response dictionary from the model.
        """
        raise NotImplementedError
