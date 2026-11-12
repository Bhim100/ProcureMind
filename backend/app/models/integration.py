"""
Integration models for third-party platforms (e.g. Zoho Books).

Stores organization connection credentials, OAuth 2.0 access and refresh tokens,
token expiry, and sync telemetry.
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ZohoIntegration(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Stores connection credentials and tokens for a Zoho Books organization.
    """

    __tablename__ = "zoho_integrations"

    organization_id: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        index=True,
        nullable=False,
        comment="Zoho Books Organization ID",
    )
    organization_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Display name of the Zoho Books organization",
    )
    access_token: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="OAuth 2.0 Bearer access token",
    )
    refresh_token: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="OAuth 2.0 Refresh token",
    )
    token_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="Exact UTC timestamp when the access token expires",
    )
    api_domain: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default="https://books.zoho.com",
        comment="Data center API root (e.g. https://books.zoho.com, https://books.zoho.in)",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
        index=True,
        comment="Whether the Zoho connection is currently active",
    )
    last_sync_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp of the most recent document sync operation",
    )

    __table_args__ = (Index("ix_zoho_integrations_active", "is_active"),)
