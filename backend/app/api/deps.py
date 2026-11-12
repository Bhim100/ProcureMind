"""Shared API dependencies for authentication, database sessions, and auditor gating."""

from fastapi import Header, HTTPException, status

from app.core.config import settings


def verify_auditor_key(x_auditor_key: str | None = Header(None, alias="X-Auditor-Key")) -> str:
    """
    Security dependency verifying the presence and validity of the server's configured AUDITOR_API_KEY.
    Fails closed if the secret is unconfigured or mismatched.

    Note: This is a shared demo authorization gate for protected auditor actions in the demo environment,
    not production multi-tenant user authentication.
    """
    if not settings.AUDITOR_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Auditor authorization key is unconfigured on server. Protected auditor actions are disabled until AUDITOR_API_KEY is configured.",
        )
    if not x_auditor_key or x_auditor_key != settings.AUDITOR_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing auditor authorization key (X-Auditor-Key header required).",
        )
    return x_auditor_key
