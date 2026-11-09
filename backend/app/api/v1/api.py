"""API router definition."""

from fastapi import APIRouter

from app.api.v1 import documents, health, invoices, matches, payments, transactions, webhooks

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(documents.router, prefix="/documents", tags=["documents"])
api_router.include_router(transactions.router, prefix="/transactions", tags=["transactions"])
api_router.include_router(matches.router, prefix="/matches", tags=["matches"])
api_router.include_router(invoices.router, prefix="/invoices", tags=["invoices"])
api_router.include_router(payments.router, prefix="/payments", tags=["payments"])
api_router.include_router(webhooks.router, prefix="/webhooks", tags=["webhooks"])
