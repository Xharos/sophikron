"""Persistent solver execution with bounded progress logs and cooperative native cancellation."""

import asyncio
import logging
import threading
from collections import deque
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select, text

from app.core.database import Database
from app.models import KholloscopeRun
from app.services.kholloscope_solver import GenerationError, generate

logger = logging.getLogger(__name__)


def run_log_lines(message: str, created_at: datetime, *, at: datetime | None = None) -> list[str]:
    """Prefix every physical line with elapsed minutes, seconds and milliseconds.

    Parameters
    ----------
    message, created_at, at
        Safe progress text, persisted queue creation and optional observation time.

    Returns
    -------
    list[str]
        Nonempty lines timestamped since submission, including any queue wait.
    """
    milliseconds = max(
        0, int(((at or datetime.now(timezone.utc)) - created_at).total_seconds() * 1000)
    )
    minutes, remainder = divmod(milliseconds, 60000)
    seconds, fraction = divmod(remainder, 1000)
    prefix = f"[{minutes:02d}:{seconds:02d}:{fraction:03d}] "
    return [prefix + line for line in message.splitlines() if line.strip()]


async def execute_run(database: Database, identifier: str) -> None:
    """Solve outside transactions, flushing logs and cancellation state every second."""
    async with database.sessions() as db, db.begin():
        row = await db.get(KholloscopeRun, identifier)
        snapshot, rules, created_at = row.snapshot, row.options, row.created_at
    messages = deque(maxlen=100)
    stop = threading.Event()

    def log(message: str) -> None:
        """Timestamp at production time rather than when the database buffer is flushed."""
        messages.extend(run_log_lines(message, created_at))

    if snapshot.get("revision_branch"):
        from app.services.kholloscope_revision_solver import generate_revision

        solver = generate_revision
    else:
        solver = generate
    task = asyncio.create_task(asyncio.to_thread(solver, snapshot, rules, log, stop))
    try:
        while not task.done():
            await asyncio.sleep(1)
            async with database.sessions() as db, db.begin():
                row = await db.get(KholloscopeRun, identifier, with_for_update=True)
                if row.status != "running":
                    stop.set()
                buffered = []
                while messages:
                    buffered.append(messages.popleft())
                row.logs = [*row.logs, *buffered][-500:]
                row.updated_at = datetime.now(timezone.utc)
        outcome, result, message = "completed", None, None
        try:
            result = await task
        except GenerationError as error:
            outcome, message = error.status, str(error)
        except Exception:
            logger.exception("Kholloscope solver failed")
            outcome, message = (
                "failed",
                "Erreur interne pendant le calcul. Consultez les journaux du serveur.",
            )
        async with database.sessions() as db, db.begin():
            row = await db.get(KholloscopeRun, identifier, with_for_update=True)
            if row.status == "running":
                row.status, row.result = outcome, result
            row.logs = [
                *row.logs,
                *messages,
                *(run_log_lines(message, created_at) if message else []),
            ][-500:]
            row.revision, row.updated_at = uuid4().hex, datetime.now(timezone.utc)
    finally:
        stop.set()
        if not task.done():
            try:
                await asyncio.shield(task)
            except (GenerationError, asyncio.CancelledError):
                pass


async def generation_maintenance(database: Database) -> None:
    """Claim jobs across API processes; recover expired heartbeats without losing draft history."""
    while True:
        try:
            identifier = None
            async with database.sessions() as db, db.begin():
                # This short advisory lock serializes claim/check operations across workers.
                await db.execute(text("SELECT pg_advisory_xact_lock(73618421)"))
                now = datetime.now(timezone.utc)
                expired = list(
                    await db.scalars(
                        select(KholloscopeRun).where(
                            KholloscopeRun.status == "running",
                            KholloscopeRun.updated_at < now - timedelta(minutes=2),
                        )
                    )
                )
                for row in expired:
                    row.status = "failed"
                    row.logs = [
                        *row.logs,
                        *run_log_lines(
                            "Calcul interrompu : exécutant indisponible. Relancez la génération.",
                            row.created_at,
                            at=now,
                        ),
                    ][-500:]
                running = await db.scalar(
                    select(KholloscopeRun.id).where(KholloscopeRun.status == "running").limit(1)
                )
                if running is None:
                    row = await db.scalar(
                        select(KholloscopeRun)
                        .where(KholloscopeRun.status == "queued")
                        .order_by(KholloscopeRun.created_at)
                        .with_for_update(skip_locked=True)
                        .limit(1)
                    )
                    if row:
                        row.status, row.updated_at = "running", now
                        identifier = row.id
            if identifier:
                await execute_run(database, identifier)
            else:
                await asyncio.sleep(2)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Kholloscope queue unavailable; retrying")
            await asyncio.sleep(5)
