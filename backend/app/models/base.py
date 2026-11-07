"""
Base SQLAlchemy configuration and mixins for ProcureMind.

This file provides:
- The declarative Base class used by all domain models.
- UUIDPrimaryKeyMixin: ensures every table gets a standard UUIDv4 primary key.
- TimestampMixin: ensures every table gets UTC timezone-aware created_at and updated_at timestamps.
- GUID and JSON_VARIANT types: ensures native PostgreSQL support while keeping SQLite fallback compatible for tests.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, String, TypeDecorator
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import JSON


def utc_now() -> datetime:
    """Helper function to return the current datetime in UTC with explicit timezone."""
    return datetime.now(UTC)


class GUID(TypeDecorator[uuid.UUID]):
    """
    Platform-independent GUID/UUID type.

    Uses PostgreSQL's native UUID type when running on PostgreSQL,
    and falls back to CHAR(36) string storage when running on SQLite.
    """

    impl = String(36)
    cache_ok = True

    def load_dialect_impl(self, dialect: Any) -> Any:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_UUID(as_uuid=True))
        return dialect.type_descriptor(String(36))

    def process_bind_param(self, value: Any, dialect: Any) -> Any:
        if value is None:
            return value
        if isinstance(value, uuid.UUID):
            return value if dialect.name == "postgresql" else str(value)
        return str(uuid.UUID(str(value)))

    def process_result_value(self, value: Any, dialect: Any) -> uuid.UUID | None:
        if value is None:
            return value
        if isinstance(value, uuid.UUID):
            return value
        return uuid.UUID(str(value))


# JSON type helper: uses JSONB on PostgreSQL and JSON on SQLite
JSON_VARIANT = JSONB().with_variant(JSON(), "sqlite")


class Base(DeclarativeBase):
    """Declarative Base class for all ProcureMind SQLAlchemy models."""


class UUIDPrimaryKeyMixin:
    """Mixin that adds a UUIDv4 primary key named `id` to any model."""

    id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
        comment="Unique identifier (UUIDv4) for this record",
    )


class TimestampMixin:
    """Mixin that adds timezone-aware created_at and updated_at timestamps in UTC."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
        comment="Timestamp when this record was created (UTC)",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
        comment="Timestamp when this record was last updated (UTC)",
    )
