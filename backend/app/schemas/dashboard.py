"""Pydantic schemas for the Overview Dashboard (Phase 11)."""

from pydantic import BaseModel, Field


class CurrencyVolume(BaseModel):
    """Financial total grouped strictly by individual currency (never cross-summed)."""

    currency: str
    payment_count: int
    total_gross: str
    total_fee: str
    total_net: str


class DemoBreakdown(BaseModel):
    """Breakdown of seeded demo records vs user-created non-demo records."""

    demo_transactions: int
    non_demo_transactions: int
    demo_documents: int
    non_demo_documents: int
    demo_payments: int
    non_demo_payments: int


class ActivityDataPoint(BaseModel):
    """Daily reconciliation activity point for the 30-day overview chart."""

    date: str  # YYYY-MM-DD
    transactions_created: int
    matches_proposed: int
    matches_approved: int
    payments_captured: int


class DashboardSummaryResponse(BaseModel):
    """Consolidated overview dashboard summary derived strictly from PostgreSQL."""

    open_records_count: int
    need_review_count: int
    sandbox_payments_count: int
    documents_by_status: dict[str, int]
    payments_by_currency: list[CurrencyVolume]
    demo_breakdown: DemoBreakdown
    recent_activity: list[ActivityDataPoint] = Field(default_factory=list)
