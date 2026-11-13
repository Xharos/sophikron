"""Statistics download tracking contracts."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.api.v1.lesson_documents import download


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
