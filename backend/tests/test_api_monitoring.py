"""Monitoring bounds, distributions and ASGI transfer/error behavior without a database."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.services.api_monitoring import (
    ApiMonitor,
    ApiMonitoringMiddleware,
    category_for,
    monitoring_timestamps,
    p95,
)
from app.services.statistics import PARIS, statistics_window


@pytest.mark.parametrize("month,day,count", [(10, 30, 1440), (3, 29, 1380), (10, 25, 1500)])
def test_daily_axis_covers_full_paris_day(month: int, day: int, count: int) -> None:
    """Include future daily buckets and respect both daylight-saving transitions."""
    now = datetime(2026, month, day, 12, tzinfo=PARIS)
    points = monitoring_timestamps(now, "day")
    assert len(points) == count
    assert points[0].astimezone(PARIS).hour == 0
    end = (points[-1] + timedelta(minutes=1)).astimezone(PARIS)
    assert end.hour == end.minute == 0
    assert end.date() == now.date() + timedelta(days=1)
    assert points[-1] > now


@pytest.mark.parametrize("period", ["week", "month"])
def test_longer_axes_keep_current_time_cutoff(period: str) -> None:
    """Keep existing week/month bounds and omit future intervals."""
    now = datetime(2026, 10, 30, 12, 34, tzinfo=PARIS)
    points = monitoring_timestamps(now, period)
    assert points[0] == statistics_window(now, period)[0]
    assert points[-1] <= now
    assert (now - points[-1]) < timedelta(hours=1 if period == "week" else 24)


def test_categories_and_histograms_are_bounded_and_keep_exact_http_codes() -> None:
    """Keep attacker paths out of labels and distinguish HTTP success from ICS authorization."""
    monitor = ApiMonitor()
    now = datetime(2026, 10, 29, 12, tzinfo=UTC)
    for status, duration in ((200, 1000), (404, 5000), (503, 100000)):
        monitor.observe("ics", status, duration, refused=status == 200, now=now)
    item = next(iter(monitor.pending.values()))
    assert item["requests"] == 3 and item["duration_us"] == 106000
    assert item["statuses"] == {"200": 1, "404": 1, "503": 1}
    assert item["ics_refused"] == 1 and item["server_errors"] == 1
    assert p95(item["histogram"], item["max_us"]) == 100
    assert p95({}, 0) is None
    for index in range(5000):
        assert category_for(f"/random/{index}", "GET") == "other"
    assert category_for("/api/v1/timetable/feed/SECRET.ics", "GET") == "ics"
    assert "SECRET" not in repr(monitor.pending)


@pytest.mark.asyncio
async def test_middleware_observes_completed_streams_and_aborted_transfers() -> None:
    """Measure completion rather than response headers alone and leave messages untouched."""
    monitor = ApiMonitor()
    scope = {
        "type": "http",
        "path": "/api/v1/lessons/1",
        "method": "GET",
        "app": SimpleNamespace(state=SimpleNamespace(api_monitor=monitor)),
    }
    sent = []

    async def send(message: dict) -> None:
        """Capture outgoing protocol messages."""
        sent.append(message)

    async def receive() -> dict:
        """Provide a completed synthetic request body."""
        return {"type": "http.request", "body": b""}

    async def application(scope: dict, receive, send) -> None:
        """Stream two response chunks with a successful final completion."""
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"one", "more_body": True})
        await send({"type": "http.response.body", "body": b"two"})

    await ApiMonitoringMiddleware(application)(scope, receive, send)
    assert len(sent) == 3
    assert next(iter(monitor.pending.values()))["incomplete"] == 0

    async def aborted(scope: dict, receive, send) -> None:
        """Fail after headers, without manufacturing a completed transfer."""
        await send({"type": "http.response.start", "status": 200, "headers": []})
        raise RuntimeError("synthetic disconnect")

    with pytest.raises(RuntimeError):
        await ApiMonitoringMiddleware(aborted)(scope, receive, send)
    item = next(iter(monitor.pending.values()))
    assert item["requests"] == 2 and item["incomplete"] == 1
    await ApiMonitoringMiddleware(application)({**scope, "path": "/health"}, receive, send)
    assert item["requests"] == 2
