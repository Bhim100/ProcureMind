"""
Document Object Storage Interface.

Defines the contract for storing and retrieving uploaded documents.
- Local filesystem implementation is used for local development and offline testing.
- Strict path containment checks prevent path-traversal attacks.
- S3-compatible private object storage (e.g. AWS S3, Cloudflare R2, MinIO) is used for hosted environments.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import BinaryIO

from app.core.config import settings


class ObjectStorageInterface(ABC):
    @abstractmethod
    def save_file(self, storage_key: str, data: BinaryIO | bytes) -> str:
        """Saves file to storage backend at the specified storage key and returns the normalized key."""

    @abstractmethod
    def get_file(self, storage_key: str) -> bytes:
        """Retrieves raw file bytes."""

    @abstractmethod
    def delete_file(self, storage_key: str) -> bool:
        """Deletes a file from storage."""


class LocalStorageService(ObjectStorageInterface):
    """
    Local filesystem storage implementation for development.

    Enforces strict path containment to prevent directory traversal attacks.
    """

    def __init__(self, base_dir: str = settings.LOCAL_STORAGE_DIR):
        self.base_dir = Path(base_dir).resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _resolve_contained_path(self, storage_key: str) -> Path:
        """
        Resolves a storage key and strictly verifies that the resulting path
        is contained within base_dir.

        Raises:
            ValueError: If the key attempts to escape the storage root.
        """
        target_path = (self.base_dir / storage_key).resolve()
        if not target_path.is_relative_to(self.base_dir):
            raise ValueError(
                f"Path containment violation: '{storage_key}' attempts to escape base storage directory"
            )
        return target_path

    def save_file(self, storage_key: str, data: BinaryIO | bytes) -> str:
        target_path = self._resolve_contained_path(storage_key)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        content = data if isinstance(data, bytes) else data.read()
        with open(target_path, "wb") as f:
            f.write(content)
        return target_path.relative_to(self.base_dir).as_posix()

    def get_file(self, storage_key: str) -> bytes:
        target_path = self._resolve_contained_path(storage_key)
        if not target_path.exists():
            raise FileNotFoundError(f"File not found: {storage_key}")
        with open(target_path, "rb") as f:
            return f.read()

    def delete_file(self, storage_key: str) -> bool:
        target_path = self._resolve_contained_path(storage_key)
        if target_path.exists():
            target_path.unlink()
            return True
        return False


def get_storage_service() -> ObjectStorageInterface:
    """Factory function for retrieving configured storage service."""
    if settings.STORAGE_BACKEND == "local":
        return LocalStorageService()
    raise NotImplementedError(
        f"Storage backend '{settings.STORAGE_BACKEND}' configured. "
        "Hosted S3 implementation will be enabled in cloud environments."
    )
