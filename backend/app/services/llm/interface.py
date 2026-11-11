"""
Abstract Base Class for LLM providers for transaction investigation.
"""

import uuid
from abc import ABC, abstractmethod
from typing import Any

from app.schemas.investigation import LLMInvestigationOutput


class LLMProviderInterface(ABC):
    """Abstract interface defining the contract for transaction investigation providers."""

    @abstractmethod
    async def investigate(
        self,
        question: str,
        context: dict[str, Any],
        discrepancy_id: uuid.UUID | None = None,
    ) -> LLMInvestigationOutput:
        """
        Generates a structured investigation explanation grounded in the provided context.

        Parameters:
            question: The inquiry or clarification request.
            context: Transaction-scoped trade, financial, and reconciliation data dictionary.
            discrepancy_id: Optional UUID of a specific discrepancy to focus analysis upon.

        Returns:
            LLMInvestigationOutput containing explanation, citations, missing facts, and recommendations.
        """
        raise NotImplementedError
