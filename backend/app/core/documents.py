"""Validated limits for private documents, independent of small authentication JSON bodies."""

import re
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

MIB = 1024 * 1024
FILE_TYPES: dict[str, tuple[int, str]] = {
    "jpg": (10 * MIB, "image/jpeg"),
    "jpeg": (10 * MIB, "image/jpeg"),
    "png": (10 * MIB, "image/png"),
    "pdf": (25 * MIB, "application/pdf"),
    "docx": (25 * MIB, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    "xlsx": (25 * MIB, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    "zip": (50 * MIB, "application/zip"),
    "py": (MIB, "text/plain"),
}


def is_document_upload(path: str, method: str) -> bool:
    """Recognize only the exact binary route for size and media-type exceptions."""
    return (
        method == "PUT"
        and re.fullmatch(r"/api/v1/lessons/[1-9][0-9]*/uploads/[0-9a-f]{32}", path) is not None
    )


class DocumentSettings(BaseSettings):
    """Keep storage, quota reservations and transfers bounded and configurable."""

    model_config = SettingsConfigDict(env_prefix="DOCUMENT_", env_file=None, frozen=True)
    root: Path = Path("/var/lib/sophikron/documents")
    course_quota_bytes: int = Field(default=1024 * MIB, ge=50 * MIB)
    user_quota_bytes: int = Field(default=5 * 1024 * MIB, ge=50 * MIB)
    total_quota_bytes: int = Field(default=20 * 1024 * MIB, ge=50 * MIB)
    reserve_bytes: int = Field(default=256 * MIB, ge=0)
    upload_timeout_seconds: int = Field(default=180, ge=5, le=300)
    max_concurrent_downloads: int = Field(default=16, ge=1, le=256)
    maintenance_enabled: bool = True

    @property
    def max_bytes(self) -> int:
        """Return the largest accepted raw file body in bytes."""
        return max(value[0] for value in FILE_TYPES.values())
