"""Background task cancellation and aggregate merging without real waiting."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.services.api_monitoring import ApiMonitor, empty_aggregate, merge_aggregate
from app.services.document_storage import document_maintenance


def test_merge_preserves_sums_maximum_and_histograms() -> None:
    """Combine independent observations without replacing counters or averaging maxima."""
    target, source = empty_aggregate(), empty_aggregate()
    target["max_us"], source["max_us"] = 12, 5
    source["statuses"][200] = 3
    source["histogram"][10] = 3
    merge_aggregate(target, source)
    assert target["max_us"] == 12
    assert target["statuses"][200] == 3 and target["histogram"][10] == 3
    assert source["statuses"][200] == 3


@pytest.mark.asyncio
async def test_monitor_flushes_before_sleep_and_propagates_cancellation() -> None:
    """Cancellation terminates the task after its first flush without an extra iteration."""
    monitor = ApiMonitor()
    database = object()
    with patch.object(monitor, "flush", new_callable=AsyncMock) as flush:
        with patch("app.services.api_monitoring.asyncio.sleep", side_effect=asyncio.CancelledError):
            with pytest.raises(asyncio.CancelledError):
                await monitor.run(database)
    flush.assert_awaited_once_with(database)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [None, OSError("storage unavailable")])
async def test_document_worker_retains_retry_after_failure(failure: Exception | None) -> None:
    """A cleanup failure still reaches the retry delay; cancellation remains observable."""
    with patch(
        "app.services.document_storage.cleanup_documents", new_callable=AsyncMock
    ) as cleanup:
        cleanup.side_effect = failure
        with patch(
            "app.services.document_storage.asyncio.sleep", side_effect=asyncio.CancelledError
        ):
            with pytest.raises(asyncio.CancelledError):
                await document_maintenance(None, None)
    cleanup.assert_awaited_once_with(None, None)
