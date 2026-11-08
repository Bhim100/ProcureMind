"""
Enumerations for ProcureMind domain models.

All enum values are lower-case string values to ensure consistency across
the database, API payloads, and internal services.
"""

from enum import Enum


class ProcessingStatus(str, Enum):
    """Lifecycle status of an ingested document."""

    UPLOADED = "uploaded"
    PARSED = "parsed"
    EXTRACTED = "extracted"
    NEEDS_REVIEW = "needs_review"
    APPROVED = "approved"
    REJECTED = "rejected"


class DocumentType(str, Enum):
    """Categorization of commercial/financial documents."""

    INVOICE = "invoice"
    SHIPPING_BILL = "shipping_bill"
    BANK_STATEMENT = "bank_statement"
    CUSTOMS_DECLARATION = "customs_declaration"
    OTHER = "other"


class ExtractionMethod(str, Enum):
    """Method used to extract a specific field value from a document."""

    TEXT = "text"  # Direct PDF text block extraction
    OCR = "ocr"  # Optical Character Recognition fallback
    LLM = "llm"  # Large Language Model structured extraction
    MANUAL = "manual"  # Manually typed or edited by human reviewer


class ReviewState(str, Enum):
    """Review and confidence state of an extracted field or decision."""

    PENDING = "pending"
    AUTO_ACCEPTED = "auto_accepted"
    HUMAN_VERIFIED = "human_verified"
    REJECTED = "rejected"


class TransactionStatus(str, Enum):
    """Overall reconciliation status of an export transaction lifecycle."""

    DRAFT = "draft"
    IN_PROGRESS = "in_progress"
    RECONCILED = "reconciled"
    DISCREPANT = "discrepant"
    CLOSED = "closed"


class PaymentStatus(str, Enum):
    """Status of a provider payment or capture."""

    PENDING = "pending"
    COMPLETED = "completed"
    REFUNDED = "refunded"
    FAILED = "failed"


class EnvironmentLabel(str, Enum):
    """Indicates whether a record comes from sandbox, simulated tests, or live systems."""

    SANDBOX = "sandbox"
    SIMULATED = "simulated"
    LIVE = "live"


class SettlementStatus(str, Enum):
    """Status of a payment provider payout batch to the merchant bank."""

    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"


class BankTransactionStatus(str, Enum):
    """Status of a bank statement line entry."""

    PENDING = "pending"
    POSTED = "posted"
    RECONCILED = "reconciled"


class BankTransactionType(str, Enum):
    """Cash flow direction on a bank statement."""

    CREDIT = "credit"  # Inflow (payment received)
    DEBIT = "debit"  # Outflow (bank charges, refunds, taxes)


class AllocationMethod(str, Enum):
    """Method used to link a payment/bank credit to an invoice."""

    AUTO_EXACT = "auto_exact"  # 100% exact reference and amount match
    RULE_HEURISTIC = "rule_heuristic"  # Matched by buyer + close date + amount
    MANUAL_HUMAN = "manual_human"  # Manually assigned by reviewer


class AllocationReviewStatus(str, Enum):
    """Review approval state of an allocation."""

    SUGGESTED = "suggested"
    APPROVED = "approved"
    REJECTED = "rejected"


class DiscrepancySeverity(str, Enum):
    """Severity level of an audit or reconciliation mismatch."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class DiscrepancyStatus(str, Enum):
    """Resolution lifecycle of a discrepancy."""

    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class DecisionType(str, Enum):
    """Action taken by a human operator in HumanDecision."""

    APPROVED = "approved"
    REJECTED = "rejected"
    OVERRIDDEN = "overridden"
    RE_ASSIGNED = "re_assigned"


class TargetType(str, Enum):
    """The type of domain entity a human decision or discrepancy targets."""

    DISCREPANCY = "discrepancy"
    ALLOCATION = "allocation"
    DOCUMENT = "document"
    TRANSACTION_LINK = "transaction_link"
    INVOICE = "invoice"
    SHIPPING_BILL = "shipping_bill"
    PAYMENT = "payment"
    SETTLEMENT = "settlement"
    BANK_TRANSACTION = "bank_transaction"


class LinkType(str, Enum):
    """Supported typed relationship pairs connecting domain trade records."""

    INVOICE_SHIPPING_BILL = "invoice_shipping_bill"
    INVOICE_PAYMENT = "invoice_payment"
    PAYMENT_SETTLEMENT = "payment_settlement"
    BANK_TRANSACTION_PAYMENT = "bank_transaction_payment"
    BANK_TRANSACTION_SETTLEMENT = "bank_transaction_settlement"


class LinkStatus(str, Enum):
    """Lifecycle review state of a trade relationship link."""

    PROPOSED = "proposed"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


class LinkMethod(str, Enum):
    """Origin method of a relationship link."""

    AUTO_EXACT = "auto_exact"
    MANUAL = "manual"
