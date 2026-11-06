"""Document Object Storage Interface.

Defines the contract for storing and retrieving uploaded documents.
- Local filesystem implementation is used for local development and offline testing.
- S3-compatible private object storage (e.g. AWS S3, Cloudflare R2, MinIO) is used for hosted environments.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import BinaryIO

from app.core.config import settings


class ObjectStorageInterface(ABC):
    @abstractmethod
    def save_file(self, file_path: str, data: BinaryIO | bytes) -> str:
        """Saves file to storage backend and returns storage key/path."""

    @abstractmethod
    def get_file(self, storage_key: str) -> bytes:
        """Retrieves raw file bytes."""

    @abstractmethod
    def get_signed_url(self, storage_key: str, expires_in_seconds: int = 300) -> str:
        """Generates a temporary signed URL or local download URL."""

    @abstractmethod
    def delete_file(self, storage_key: str) -> bool:
        """Deletes a file from storage."""


class LocalStorageService(ObjectStorageInterface):
    """Local filesystem storage implementation for development."""

    def __init__(self, base_dir: str = settings.LOCAL_STORAGE_DIR):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def save_file(self, file_path: str, data: BinaryIO | bytes) -> str:
        target_path = self.base_dir / file_path
        target_path.parent.mkdir(parents=True, exist_ok=True)
        content = data if isinstance(data, bytes) else data.read()
        with open(target_path, "wb") as f:
            f.write(content)
        return str(target_path.relative_to(self.base_dir))

    def get_file(self, storage_key: str) -> bytes:
        target_path = self.base_dir / storage_key
        if not target_path.exists():
            raise FileNotFoundError(f"File not found: {storage_key}")
        with open(target_path, "rb") as f:
            return f.read()

    def get_signed_url(self, storage_key: str, expires_in_seconds: int = 300) -> str:
        # Local development fallback URL
        return f"/api/v1/documents/local/{storage_key}"

    def delete_file(self, storage_key: str) -> bool:
        target_path = self.base_dir / storage_key
        if target_path.exists():
            target_path.unlink()
            return True
        return False


def get_storage_service() -> ObjectStorageInterface:
    """Factory function for retrieving configured storage service."""
    if settings.STORAGE_BACKEND == "local":
        return LocalStorageService()
    # In hosted environments with S3:
    raise NotImplementedError(
        f"Storage backend '{settings.STORAGE_BACKEND}' configured. "
        "Hosted S3 implementation will be enabled in Phase 1."
    )
