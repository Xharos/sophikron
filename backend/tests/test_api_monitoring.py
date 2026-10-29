"""Monitoring bounds, distributions and ASGI transfer/error behavior without a database."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.services.api_monitoring import ApiMonitor, ApiMonitoringMiddleware, category_for, p95


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
