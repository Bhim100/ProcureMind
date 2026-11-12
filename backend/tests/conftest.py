"""
Pytest configuration and shared fixtures for ProcureMind backend tests.
"""

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.database import get_db
from app.main import app
from app.models.base import Base


@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    if "sqlite" in type(dbapi_connection).__module__:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


@pytest.fixture(scope="session")
def test_engine():
    """
    Creates an isolated in-memory SQLite engine for automated unit tests.
    StaticPool ensures all threads/connections share the exact same in-memory database.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # Create all tables defined on Base.metadata
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def db_session(test_engine) -> Generator[Session, None, None]:
    """
    Provides a transactional database session rolled back after every individual test.
    This guarantees zero test crosstalk.
    """
    connection = test_engine.connect()
    transaction = connection.begin()
    session_factory = sessionmaker(bind=connection)
    session = session_factory()

    try:
        yield session
    finally:
        session.close()
        if transaction.is_active:
            transaction.rollback()
        connection.close()


@pytest.fixture(scope="function")
def client_with_db(db_session: Session) -> Generator[TestClient, None, None]:
    """Provides a TestClient overriding get_db with the test database session."""

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    original_secret = settings.STORAGE_SIGNING_SECRET
    settings.STORAGE_SIGNING_SECRET = "test-only-signing-secret-key-32bytes!!"
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        settings.STORAGE_SIGNING_SECRET = original_secret
