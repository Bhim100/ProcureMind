"""
ProcureMind Domain Models.

This package exposes all SQLAlchemy domain entities and enums for the
authoritative PostgreSQL database.
"""

from app.models.base import GUID, JSON_VARIANT, Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.document import Document, ExtractedField
from app.models.enums import (
    AllocationMethod,
    AllocationReviewStatus,
    BankTransactionStatus,
    BankTransactionType,
    DecisionType,
    DiscrepancySeverity,
    DiscrepancyStatus,
    DocumentType,
    EnvironmentLabel,
    ExtractionMethod,
    LinkMethod,
    LinkStatus,
    LinkType,
    PaymentStatus,
    ProcessingStatus,
    ReviewState,
    SettlementStatus,
    TargetType,
    TransactionStatus,
)
from app.models.export import ExportTransaction, Invoice, InvoiceLineItem, ShippingBill
from app.models.payment import BankTransaction, Payment, ProviderWebhookEvent, Settlement
from app.models.reconciliation import Allocation, Discrepancy, EvidenceReference, HumanDecision
from app.models.relationship import TransactionLink

__all__ = [
    "GUID",
    "JSON_VARIANT",
    # Reconciliation & Audit
    "Allocation",
    # Enums
    "AllocationMethod",
    "AllocationReviewStatus",
    # Payments & Settlements
    "BankTransaction",
    "BankTransactionStatus",
    "BankTransactionType",
    # Base & Types
    "Base",
    "DecisionType",
    "Discrepancy",
    "DiscrepancySeverity",
    "DiscrepancyStatus",
    # Documents
    "Document",
    "DocumentType",
    "EnvironmentLabel",
    "EvidenceReference",
    # Export & Billing
    "ExportTransaction",
    "ExtractedField",
    "ExtractionMethod",
    "HumanDecision",
    "Invoice",
    "InvoiceLineItem",
    # Relationships
    "LinkMethod",
    "LinkStatus",
    "LinkType",
    "Payment",
    "PaymentStatus",
    "ProcessingStatus",
    "ProviderWebhookEvent",
    "ReviewState",
    "Settlement",
    "SettlementStatus",
    "ShippingBill",
    "TargetType",
    "TimestampMixin",
    "TransactionLink",
    "TransactionStatus",
    "UUIDPrimaryKeyMixin",
]
