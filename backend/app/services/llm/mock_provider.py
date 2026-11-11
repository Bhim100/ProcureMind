"""
Deterministic mock LLM provider for Phase 6 automated testing.
Ensures zero live network calls during automated testing (AGENTS.md Rule 6).
"""

import uuid
from typing import Any

import httpx

from app.schemas.investigation import LLMInvestigationOutput
from app.services.llm.interface import LLMProviderInterface


class MockLLMProvider(LLMProviderInterface):
    """Deterministic, testable LLM provider for test suites and offline verification."""

    provider_name = "mock"

    def __init__(
        self,
        simulate_error: str | None = None,
        custom_cited_ids: list[str] | None = None,
    ):
        self.simulate_error = simulate_error
        self.custom_cited_ids = custom_cited_ids

    async def investigate(
        self,
        question: str,
        context: dict[str, Any],
        discrepancy_id: uuid.UUID | None = None,
    ) -> LLMInvestigationOutput:
        # 1. Error simulation hooks
        if self.simulate_error == "timeout":
            req = httpx.Request("POST", "https://mock.llm/v1/investigate")
            raise httpx.ReadTimeout("Mock LLM connection timed out", request=req)
        elif self.simulate_error == "http_error":
            req = httpx.Request("POST", "https://mock.llm/v1/investigate")
            resp = httpx.Response(502, request=req)
            raise httpx.HTTPStatusError(
                "502 Bad Gateway from upstream LLM", request=req, response=resp
            )
        elif self.simulate_error == "malformed_json":
            raise ValueError("Malformed JSON received from model: Expecting value: line 1 column 1")

        q_lower = question.lower()

        # 2. Policy Refusal checks (Prompt injection / unauthorized financial actions)
        prohibited_terms = [
            "approve this payment",
            "approve payment",
            "approve the match",
            "disburse funds",
            "disburse",
            "change balance",
            "alter invoice",
            "set total to",
            "claim real export remittance",
            "proves real export remittance",
            "ignore previous instructions",
        ]
        if any(term in q_lower for term in prohibited_terms):
            return LLMInvestigationOutput(
                explanation=(
                    "Policy Refusal: AI assistants are strictly prohibited from autonomously "
                    "approving matches, disbursing financial proceeds, altering balances, or claiming "
                    "that PayPal Sandbox payments constitute official export remittances. In accordance "
                    "with ProcureMind governance, all financial allocations require human auditor authorization."
                ),
                cited_record_ids=[],
                missing_information=[],
                suggested_next_action="Submit the transaction records to an authorized human auditor via the Review Workspace.",
                draft_clarification_message=None,
                requires_human_review=True,
                policy_refusal=True,
            )

        # 3. Context Analysis
        invoices = context.get("invoices", [])
        payments = context.get("payments", [])
        shipping_bills = context.get("shipping_bills", [])
        discrepancies = context.get("discrepancies", [])

        cited_ids: list[str] = []
        if self.custom_cited_ids is not None:
            cited_ids = list(self.custom_cited_ids)
        else:
            for inv in invoices:
                if "id" in inv:
                    cited_ids.append(str(inv["id"]))
            for pay in payments:
                if "id" in pay:
                    cited_ids.append(str(pay["id"]))

        missing_info: list[str] = []
        if not shipping_bills:
            missing_info.append("Customs Shipping Bill declaration")

        # 4. Scenario-specific grounded logic
        if discrepancies:
            target_disc = discrepancies[0]
            if discrepancy_id:
                for d in discrepancies:
                    if str(d.get("id")) == str(discrepancy_id):
                        target_disc = d
                        break

            disc_desc = target_disc.get("description", "Active discrepancy identified.")
            calc = target_disc.get("calculation", {})
            rem = calc.get("unexplained_remainder", "unknown")

            missing_info.append(f"Documentation explaining the remaining {rem} difference")

            explanation = (
                f"Investigation of transaction {context.get('transaction_reference', 'unknown')}: "
                f"{disc_desc} Specifically, an unexplained remainder of {rem} was identified "
                f"between invoice total and payment proceeds. This calculation was determined by the "
                f"Phase 4 reconciliation engine and requires human auditor review."
            )
            suggested_action = (
                target_disc.get("recommended_action")
                or "Audit the payment deduction or request a revised commercial invoice."
            )
            draft_msg = (
                f"Dear Counterparty,\n\nRegarding transaction {context.get('transaction_reference')}, "
                f"we note an unexplained remainder of {rem} between the invoice and received proceeds. "
                f"Please provide clarification or documentation supporting this deduction.\n\nRegards,\nProcureMind Auditor"
            )
        else:
            # Clean transaction scenario
            explanation = (
                f"Transaction {context.get('transaction_reference', 'unknown')} has no active discrepancies. "
                f"All recorded invoice amounts and payment proceeds align with documented fee structures."
            )
            suggested_action = "Review for final human auditor sign-off and ledger posting."
            draft_msg = None

        return LLMInvestigationOutput(
            explanation=explanation,
            cited_record_ids=cited_ids,
            missing_information=missing_info,
            suggested_next_action=suggested_action,
            draft_clarification_message=draft_msg,
            requires_human_review=True,
            policy_refusal=False,
        )
