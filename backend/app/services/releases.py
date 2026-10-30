"""Bounded GitHub lookup and daily PostgreSQL cache for administrator version tracking."""

import json
import re
from datetime import datetime, timedelta
from importlib.metadata import version
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

import anyio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.releases import ReleaseCheck

REPOSITORY = "https://github.com/Xharos/sophikron"
API_URL = "https://api.github.com/repos/Xharos/sophikron/releases/latest"
VERSION_PATTERN = re.compile(r"v?(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")


def stable_version(value: str) -> tuple[int, int, int] | None:
    """Return numeric stable version parts, or None for unsupported release tags."""
    match = VERSION_PATTERN.fullmatch(value)
    return tuple(map(int, match.groups())) if match else None


def fetch_release() -> tuple[str, str] | None:
    """Fetch one stable public release with a timeout and a bounded response body."""
    request = Request(API_URL, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "Sophikron-update-check",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    try:
        with urlopen(request, timeout=4) as response:
            body = response.read(262145)
    except HTTPError as error:
        if error.code == 404:
            return None
        raise
    if len(body) > 262144:
        raise ValueError("Release response too large")
    data = json.loads(body)
    tag = data.get("tag_name")
    if (
        not isinstance(tag, str) or len(tag) > 100 or stable_version(tag) is None
        or data.get("draft") is not False or data.get("prerelease") is not False
    ):
        raise ValueError("Unsupported stable release")
    return tag.removeprefix("v"), f"{REPOSITORY}/releases/tag/{quote(tag, safe='')}"


def backend_build() -> dict[str, str | None]:
    """Read the installed package version and revision embedded in its Docker image."""
    revision_file = Path(__file__).parents[1] / "core" / "revision.txt"
    revision = revision_file.read_text().strip() if revision_file.exists() else ""
    return {
        "version": version("sophikron-api"),
        "revision": revision if re.fullmatch(r"[0-9a-f]{40}(-dirty)?", revision) else None,
    }


async def release_status(db: AsyncSession, now: datetime) -> dict:
    """Refresh an expired cache once across workers; caller owns the transaction.

    Parameters
    ----------
    db
        Authorized request session with an open transaction.
    now
        Timezone-aware current time.

    Returns
    -------
    dict
        Installed backend metadata and persisted release status, including stale errors.
    """
    locked = await db.scalar(text("SELECT pg_try_advisory_xact_lock(73482916)"))
    row = await db.get(ReleaseCheck, 1, populate_existing=True)
    if row is None:
        raise RuntimeError("Release cache migration is missing")
    if locked and (row.attempted_at is None or now - row.attempted_at >= timedelta(days=1)):
        row.attempted_at = now
        try:
            release = await anyio.to_thread.run_sync(fetch_release)
        except (URLError, OSError, ValueError, TypeError, AttributeError):
            row.error = "La vérification GitHub est indisponible."
        else:
            row.version, row.release_url = release if release else (None, None)
            row.checked_at = now
            row.error = None
        await db.flush()
    return {
        "backend": backend_build(),
        "latest_version": row.version,
        "release_url": row.release_url,
        "attempted_at": row.attempted_at,
        "checked_at": row.checked_at,
        "error": row.error,
    }
