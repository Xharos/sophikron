"""Calendar boundaries, safe storage metering and completed-transfer instrumentation."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest

from app.api.v1.lesson_documents import download
from app.core.documents import DocumentSettings
from app.services.statistics import folder_usage, statistics_window


@pytest.mark.parametrize("day,hours", [("2027-03-28", 23), ("2026-10-25", 25), ("2026-10-26", 24)])
def test_statistics_paris_calendar_hours(day: str, hours: int) -> None:
    """Keep both repeated hours and omit the nonexistent spring hour without shifting days."""
    now = datetime.fromisoformat(day + "T23:59:59").replace(tzinfo=ZoneInfo("Europe/Paris"))
    start, bins = statistics_window(now, "day")
    assert len(bins) == hours and start == bins[0]
    assert len(set(bins)) == hours
    assert all(item.astimezone(ZoneInfo("Europe/Paris")).date().isoformat() == day for item in bins)


def test_today_does_not_fabricate_zero_activity_in_future_hours() -> None:
    """Stop at the current partial hour rather than drawing a drop to zero in the future."""
    now = datetime(2026, 10, 26, 2, 30, tzinfo=ZoneInfo("Europe/Paris"))
    _, bins = statistics_window(now, "day")
    assert len(bins) == 3 and all(item <= now for item in bins)


@pytest.mark.parametrize("period,days", [("week", 7), ("month", 30)])
def test_statistics_calendar_days(period: str, days: int) -> None:
    """Include today and preceding calendar days across daylight-saving transitions."""
    now = datetime(2026, 10, 26, 0, 10, tzinfo=UTC)
    start, bins = statistics_window(now, period)
    assert start == bins[0] and len(bins) == days
    assert bins[-1].astimezone(ZoneInfo("Europe/Paris")).date() == now.date()
    assert all(item.astimezone(ZoneInfo("Europe/Paris")).hour == 0 for item in bins)


def test_statistics_measure_only_document_folders(tmp_path: Path) -> None:
    """Do not confuse whole-filesystem usage, unrelated root files or directories with documents."""
    settings = DocumentSettings(root=tmp_path)
    assert folder_usage(settings) == (0, 0)
    (tmp_path / "objects").mkdir()
    (tmp_path / "temporary").mkdir()
    (tmp_path / "objects" / "document").write_bytes(b"12345")
    (tmp_path / "objects" / "nested").mkdir()
    (tmp_path / "temporary" / "upload").write_bytes(b"123")
    (tmp_path / "unrelated").write_bytes(b"do not count")
    assert folder_usage(settings) == (5, 3)


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["complete", "short", "cancelled", "failed"])
async def test_only_completed_transfers_are_counted(outcome: str) -> None:
    """Never count an interrupted or short stream and always close the document handle."""
    source = AsyncMock()
    source.read.side_effect = {
        "complete": [b"data", b""],
        "short": [b"da", b""],
        "cancelled": [b"da", asyncio.CancelledError()],
        "failed": [OSError("interrupted")],
    }[outcome]
    file = SimpleNamespace(
        id=2, lesson_id=1, original_name="document.py", media_type="text/plain", size_bytes=4
    )
    service = SimpleNamespace(
        download=AsyncMock(return_value=(file, source)), record_download=AsyncMock()
    )
    actor = SimpleNamespace(id=3)
    response = await download(1, 2, actor, service)
    if outcome in {"cancelled", "failed"}:
        with pytest.raises(asyncio.CancelledError if outcome == "cancelled" else OSError):
            async for _chunk in response.body_iterator:
                pass
    else:
        chunks = [chunk async for chunk in response.body_iterator]
        assert b"".join(chunks) == (b"data" if outcome == "complete" else b"da")
    assert service.record_download.await_count == int(outcome == "complete")
    source.aclose.assert_awaited_once()
