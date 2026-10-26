"""Private disk operations, bounded content validation and recoverable file deletion."""

import asyncio
import hashlib
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import anyio
from sqlalchemy import delete, select

from app.core.database import Database
from app.core.documents import DocumentSettings
from app.models.lessons import LessonFile, LessonFileDeletion, LessonUpload
from app.services.errors import AuthError

logger = logging.getLogger(__name__)


class DocumentStorage:
    """Use generated keys only; disk paths never depend on original filenames."""

    def __init__(self, settings: DocumentSettings) -> None:
        """Bind immutable settings without touching the filesystem."""
        self.settings = settings

    def path(self, key: str, *, temporary: bool = False) -> Path:
        """Return a confined path and reject malformed keys or symbolic-link paths."""
        if not re.fullmatch(r"[0-9a-f]{32}", key):
            raise ValueError("Invalid storage key")
        root = self.settings.root.resolve()
        folder = root / ("temporary" if temporary else "objects")
        candidate = folder / key
        if (
            folder.is_symlink()
            or candidate.is_symlink()
            or not candidate.resolve().is_relative_to(root)
        ):
            raise ValueError("Unsafe storage path")
        return candidate

    def prepare(self, size: int) -> None:
        """Create private storage directories and preserve a free-space reserve."""
        for folder in (
            self.settings.root,
            self.settings.root / "objects",
            self.settings.root / "temporary",
        ):
            if folder.is_symlink():
                raise OSError("Symbolic storage directory")
            folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        if shutil.disk_usage(self.settings.root).free < size + self.settings.reserve_bytes:
            raise AuthError(507, "Espace documentaire insuffisant.")

    async def receive(self, key: str, stream: AsyncIterator[bytes], expected_size: int) -> str:
        """Write and hash a raw bounded stream without collecting the body in memory."""
        await anyio.to_thread.run_sync(self.prepare, expected_size)
        target = self.path(key, temporary=True)
        digest = hashlib.sha256()
        size = 0
        async with await anyio.open_file(target, "xb") as output:
            async with asyncio.timeout(self.settings.upload_timeout_seconds):
                async for chunk in stream:
                    size += len(chunk)
                    if size > expected_size:
                        raise AuthError(413, "Le fichier dépasse la taille annoncée.")
                    digest.update(chunk)
                    await output.write(chunk)
            await output.flush()
            await anyio.to_thread.run_sync(os.fsync, output.wrapped.fileno())
        if size != expected_size:
            raise AuthError(422, "Le transfert du fichier est incomplet.")
        return digest.hexdigest()

    async def validate(self, key: str, extension: str) -> str:
        """Inspect file structure in a bounded child process without executing uploaded code."""
        path = self.path(key, temporary=True)

        def inspect() -> subprocess.CompletedProcess[bytes]:
            """Bound parser execution on Linux and Windows, including selector event loops."""
            return subprocess.run(
                [sys.executable, "-m", "app.services.file_validation", str(path), extension],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=30,
                check=False,
            )

        try:
            result = await anyio.to_thread.run_sync(inspect)
        except subprocess.TimeoutExpired:
            raise AuthError(422, "Le fichier est trop complexe pour être validé.") from None
        if result.returncode:
            raise AuthError(422, "Le contenu du fichier ne correspond pas au format autorisé.")
        return result.stdout.decode().strip()

    def publish(self, key: str) -> None:
        """Rename within one volume before SQL publication; orphan reconciliation covers crashes."""
        os.replace(self.path(key, temporary=True), self.path(key))
        if os.name == "posix":
            descriptor = os.open(self.path(key).parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)

    def remove(self, key: str, *, temporary: bool = False) -> None:
        """Idempotently delete one confined file; propagate failures for durable retry."""
        self.path(key, temporary=temporary).unlink(missing_ok=True)


async def cleanup_documents(database: Database, storage: DocumentStorage) -> None:
    """Drain committed deletions and expired uploads, then reconcile old orphan objects."""
    async with database.sessions.begin() as session:
        jobs = list(
            (
                await session.scalars(
                    select(LessonFileDeletion).limit(100).with_for_update(skip_locked=True)
                )
            ).all()
        )
        for job in jobs:
            try:
                await anyio.to_thread.run_sync(storage.remove, job.storage_key)
            except (OSError, ValueError):
                job.attempts += 1
                logger.warning("Document deletion failed; durable retry retained")
            else:
                await session.delete(job)
        await session.execute(
            delete(LessonUpload).where(LessonUpload.expires_at < datetime.now(UTC))
        )
    # Files younger than a day may still belong to an in-flight transaction.
    async with database.sessions() as session:
        live = set((await session.scalars(select(LessonFile.storage_key))).all())
    cutoff = time.time() - 86400

    def reconcile() -> None:
        """Remove only old generated keys; never recursively purge a storage directory."""
        for temporary in (True, False):
            folder = storage.settings.root / ("temporary" if temporary else "objects")
            if not folder.is_dir() or folder.is_symlink():
                continue
            for path in folder.iterdir():
                if re.fullmatch(r"[0-9a-f]{32}", path.name) and not path.is_symlink():
                    if path.stat().st_mtime < cutoff and (temporary or path.name not in live):
                        storage.remove(path.name, temporary=temporary)

    await anyio.to_thread.run_sync(reconcile)


async def document_maintenance(database: Database, storage: DocumentStorage) -> None:
    """Retry durable cleanup every thirty seconds for the application lifetime."""
    while True:
        try:
            await cleanup_documents(database, storage)
        except Exception:
            logger.warning("Document maintenance unavailable; pending work retained")
        await asyncio.sleep(30)
