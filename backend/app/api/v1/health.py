from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.config import settings
from app.core.database import check_db_connection

router = APIRouter()


class HealthResponse(BaseModel):
    status: str
    service: str
    environment: str
    timestamp: datetime


class ReadinessResponse(BaseModel):
    status: str
    service: str
    environment: str
    database: dict[str, Any]
    storage: dict[str, Any]
    secondary_services: dict[str, Any]
    timestamp: datetime


@router.get("/health", response_model=HealthResponse)
def get_health() -> HealthResponse:
    """Liveness probe to confirm backend is serving traffic."""
    return HealthResponse(
        status="ok",
        service=settings.APP_NAME,
        environment=settings.ENVIRONMENT,
        timestamp=datetime.now(UTC),
    )


@router.get("/ready", response_model=ReadinessResponse)
def get_readiness() -> ReadinessResponse:
    """Readiness probe checking database connectivity and dependent subsystems."""
    db_status = check_db_connection()
    is_ready = db_status["status"] == "connected"

    return ReadinessResponse(
        status="ready" if is_ready else "degraded",
        service=settings.APP_NAME,
        environment=settings.ENVIRONMENT,
        database=db_status,
        storage={
            "backend": settings.STORAGE_BACKEND,
            "status": "ready",
        },
        secondary_services={
            "falkordb": "enabled" if settings.FALKORDB_ENABLED else "disabled (optional)",
            "chroma": "enabled" if settings.CHROMA_ENABLED else "disabled (optional)",
        },
        timestamp=datetime.now(UTC),
    )
