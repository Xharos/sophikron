"""Real bounded-memory document reception at multiple transfer sizes."""

import hashlib
import tracemalloc
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from time import perf_counter

import pytest

from app.core.documents import DocumentSettings
from app.services.document_storage import DocumentStorage

pytestmark = pytest.mark.perf


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [1024 * 1024, 16 * 1024 * 1024])
async def test_streaming_memory_and_time_budget(
    tmp_path: Path,
    size: int,
    record_property: Callable[[str, object], None],
) -> None:
    """Hash every byte while avoiding a Python allocation proportional to the entire upload."""
    chunk = b"x" * (64 * 1024)
    expected = hashlib.sha256()
    for _ in range(size // len(chunk)):
        expected.update(chunk)

    async def stream() -> AsyncIterator[bytes]:
        """Yield fixed-size chunks without building the complete payload in memory."""
        for _ in range(size // len(chunk)):
            yield chunk

    storage = DocumentStorage(DocumentSettings(root=tmp_path, reserve_bytes=0))
    key = "a" * 32
    tracemalloc.start()
    try:
        start = perf_counter()
        digest = await storage.receive(key, stream(), size)
        elapsed = perf_counter() - start
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert digest == expected.hexdigest()
    assert storage.path(key, temporary=True).stat().st_size == size
    record_property("bytes", size)
    record_property("peak_python_bytes", peak)
    record_property("elapsed_seconds", elapsed)
    assert peak < 8 * 1024 * 1024
    assert elapsed < 15
