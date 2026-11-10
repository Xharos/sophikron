"""Exercise real structural validators and private storage without executing uploaded content."""

import asyncio
import hashlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zipfile import ZipFile

import anyio
import pytest
from fastapi import FastAPI, HTTPException, Request
from PIL import Image
from pydantic import ValidationError
from pypdf import PdfWriter

from app.api.v1.lesson_documents import download, download_slot, get_documents, router
from app.core.documents import DocumentSettings, is_document_upload
from app.dependencies.auth import get_current_user
from app.models.lessons import LessonFile
from app.schemas.lessons import ElementCreate
from app.services.document_storage import DocumentStorage
from app.services.errors import AuthError
from app.services.file_validation import validate_file


def test_author_selected_columns_and_binary_route_boundaries() -> None:
    """Treat column titles as arbitrary labels and constrain the binary exception to one route."""
    table = ElementCreate(
        kind="table",
        title="Dossiers",
        table_columns=["  Méthodes ", "Travaux pratiques"],
        expected_version=0,
    )
    assert table.table_columns == ["Méthodes", "Travaux pratiques"]
    assert is_document_upload("/api/v1/lessons/2/uploads/" + "a" * 32, "PUT")
    assert not is_document_upload("/api/v1/auth/login", "PUT")
    assert not is_document_upload("/api/v1/lessons/2/uploads/" + "a" * 32 + "/other", "PUT")


def test_real_image_pdf_office_archive_and_python_validation(tmp_path: Path) -> None:
    """Accept supported actual structures and refuse spoofed extensions without execution."""
    image = tmp_path / "image"
    Image.new("RGB", (12, 12)).save(image, format="PNG")
    assert validate_file(image, "png") == "image/png"
    with pytest.raises(ValueError):
        validate_file(image, "jpg")
    pdf = tmp_path / "pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.write(pdf)
    assert validate_file(pdf, "pdf") == "application/pdf"
    for extension, main in (("docx", "word/document.xml"), ("xlsx", "xl/workbook.xml")):
        document = tmp_path / extension
        with ZipFile(document, "w") as archive:
            archive.writestr(
                "[Content_Types].xml",
                '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>',
            )
            archive.writestr(main, "<document/>")
        assert "openxmlformats" in validate_file(document, extension)
    code = tmp_path / "code"
    code.write_text('raise RuntimeError("must never execute")', encoding="utf-8")
    assert validate_file(code, "py") == "text/plain"
    code.write_bytes(b"\x00binary")
    with pytest.raises(ValueError):
        validate_file(code, "py")


@pytest.mark.parametrize(
    "name", ["../evil.py", "/evil.py", "folder\\evil.py", "nested.zip", "vbaProject.bin"]
)
def test_reject_dangerous_archive_entries(tmp_path: Path, name: str) -> None:
    """Reject traversal, nested archives and macro payloads before any archive extraction."""
    path = tmp_path / "archive"
    with ZipFile(path, "w") as archive:
        archive.writestr(name, "content")
    if name == "folder\\evil.py":
        path.write_bytes(path.read_bytes().replace(b"folder/evil.py", b"folder\\evil.py"))
    with pytest.raises(ValueError):
        validate_file(path, "zip")


def test_reject_office_macro_parts_under_a_docx_extension(tmp_path: Path) -> None:
    """Detect macro content types independently of a renamed payload's filename."""
    path = tmp_path / "office"
    with ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", "<document/>")
        archive.writestr(
            "[Content_Types].xml",
            '<Types><Override ContentType="application/vnd.ms-office.vbaProject"/></Types>',
        )
        archive.writestr("word/renamed.bin", "opaque macro part")
    with pytest.raises(ValueError, match="macros"):
        validate_file(path, "docx")


@pytest.mark.asyncio
async def test_stream_hash_size_and_path_confinement(tmp_path: Path) -> None:
    """Hash actual chunks, reject over/under-sized transfers and exclude user-controlled paths."""
    storage = DocumentStorage(DocumentSettings(root=tmp_path, reserve_bytes=0))

    async def chunks() -> AsyncIterator[bytes]:
        """Yield a binary transfer in independent chunks."""
        yield b"first"
        yield b"second"

    key = "a" * 32
    assert await storage.receive(key, chunks(), 11) == hashlib.sha256(b"firstsecond").hexdigest()
    storage.publish(key)
    assert storage.path(key).read_bytes() == b"firstsecond"
    for expected, status in ((10, 413), (12, 422)):
        with pytest.raises(AuthError) as raised:
            await storage.receive(f"{expected:032x}", chunks(), expected)
        assert raised.value.status == status
    with pytest.raises(ValueError):
        storage.path("../outside")
    storage.remove(key)
    storage.remove(key)


@pytest.mark.asyncio
async def test_structural_validation_and_publication(tmp_path: Path) -> None:
    """Run the actual parser subprocess and publish valid bytes without a network service."""
    storage = DocumentStorage(DocumentSettings(root=tmp_path, reserve_bytes=0))
    payload = b'raise RuntimeError("uploaded code must never execute")\n'

    async def chunks() -> AsyncIterator[bytes]:
        """Yield inert Python source for the real storage pipeline."""
        yield payload

    key = "b" * 32
    await storage.receive(key, chunks(), len(payload))
    assert await storage.validate(key, "py") == "text/plain"
    with pytest.raises(AuthError) as raised:
        await storage.validate(key, "png")
    assert raised.value.status == 422
    storage.publish(key)
    assert storage.path(key).read_bytes() == payload
    assert not storage.path(key, temporary=True).exists()


@pytest.mark.asyncio
async def test_cancelled_download_closes_the_open_file(tmp_path: Path) -> None:
    """Close the actual file even when a disconnected response cancels its stream cleanup."""
    path = tmp_path / "attachment"
    path.write_bytes(b"lesson attachment")
    source = await anyio.open_file(path, "rb")
    service = AsyncMock()
    service.download.return_value = (
        LessonFile(original_name="cours.py", media_type="text/plain", size_bytes=17),
        source,
    )
    response = await download(1, 1, AsyncMock(), service)
    try:
        assert await anext(response.body_iterator) == b"lesson attachment"
        with anyio.CancelScope() as scope:
            scope.cancel()
            await response.body_iterator.aclose()
        assert source.wrapped.closed
    finally:
        await source.aclose()


def test_download_limit_comes_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Read a positive global capacity from DOCUMENT_* without accepting a disabled limiter."""
    monkeypatch.setenv("DOCUMENT_MAX_CONCURRENT_DOWNLOADS", "3")
    assert DocumentSettings().max_concurrent_downloads == 3
    for value in ("0", "-1", "257", "invalid"):
        monkeypatch.setenv("DOCUMENT_MAX_CONCURRENT_DOWNLOADS", value)
        with pytest.raises(ValidationError):
            DocumentSettings()


@pytest.mark.asyncio
@pytest.mark.parametrize("capacity", [1, 2])
async def test_download_queue_is_fifo_without_account_limits(capacity: int) -> None:
    """Start same-account requests in arrival order as global capacity becomes available."""
    slots = anyio.Semaphore(capacity, max_value=capacity)
    actor = AsyncMock()
    entered: list[int] = []
    release = [anyio.Event() for _ in range(3)]

    async def worker(index: int) -> None:
        """Hold one simulated response until the test permits its completion."""

        async def receive() -> dict[str, str]:
            """Keep this client connected while it waits."""
            await anyio.sleep_forever()
            return {"type": "http.disconnect"}

        request = Request(
            {
                "type": "http",
                "app": SimpleNamespace(state=SimpleNamespace(document_download_slots=slots)),
            },
            receive,
        )
        async with asynccontextmanager(download_slot)(request, actor):
            entered.append(index)
            await release[index].wait()

    with anyio.fail_after(5):
        async with anyio.create_task_group() as tasks:
            for index in range(3):
                tasks.start_soon(worker, index)
                await anyio.wait_all_tasks_blocked()
            assert entered == list(range(capacity))
            assert slots.statistics().tasks_waiting == 3 - capacity
            for index in range(3):
                release[index].set()
                await anyio.wait_all_tasks_blocked()
                assert entered == list(range(min(3, capacity + index + 1)))
    assert slots.value == capacity


@pytest.mark.asyncio
async def test_failed_download_releases_global_capacity() -> None:
    """Return a permit after file preparation fails, so the next queued request can proceed."""
    slots = anyio.Semaphore(1, max_value=1)

    async def receive() -> dict[str, str]:
        """Keep the request connected until its failure is returned."""
        await anyio.sleep_forever()
        return {"type": "http.disconnect"}

    request = Request(
        {
            "type": "http",
            "app": SimpleNamespace(state=SimpleNamespace(document_download_slots=slots)),
        },
        receive,
    )
    with pytest.raises(AuthError):
        async with asynccontextmanager(download_slot)(request, AsyncMock()):
            raise AuthError(404, "Document introuvable.")
    assert slots.value == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("disconnect", [True, False])
async def test_abandoned_download_leaves_the_queue(disconnect: bool) -> None:
    """Remove disconnected or cancelled waiters without leaking or consuming an active slot."""
    slots = anyio.Semaphore(1, max_value=1)
    await slots.acquire()
    abandoned = anyio.Event()

    async def receive() -> dict[str, str]:
        """Notify the queue of a real ASGI disconnect."""
        await abandoned.wait()
        return {"type": "http.disconnect"}

    request = Request(
        {
            "type": "http",
            "app": SimpleNamespace(state=SimpleNamespace(document_download_slots=slots)),
        },
        receive,
    )

    async def wait() -> None:
        """Fail if an abandoned request reaches file preparation."""
        async with asynccontextmanager(download_slot)(request, AsyncMock()):
            pytest.fail("Abandoned download started")

    with anyio.fail_after(5):
        task = asyncio.create_task(wait())
        await anyio.wait_all_tasks_blocked()
        assert slots.statistics().tasks_waiting == 1
        if disconnect:
            abandoned.set()
            with pytest.raises(HTTPException) as raised:
                await task
            assert raised.value.status_code == 499
        else:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
    assert slots.value == 0 and slots.statistics().tasks_waiting == 0
    slots.release()
    assert slots.value == 1


@pytest.mark.asyncio
async def test_http_download_holds_capacity_until_the_response_is_sent(tmp_path: Path) -> None:
    """Exercise FastAPI request-scope cleanup with a slow ASGI consumer and actual open files."""
    path = tmp_path / "file"
    path.write_bytes(b"attachment")
    slots = anyio.Semaphore(1, max_value=1)
    app = FastAPI()
    app.state.document_download_slots = slots
    app.include_router(router)
    actor = AsyncMock()
    service = AsyncMock()

    async def open_document(*args: object) -> tuple[LessonFile, anyio.AsyncFile[bytes]]:
        """Open a fresh file for each admitted request."""
        return (
            LessonFile(original_name="cours.py", media_type="text/plain", size_bytes=10),
            await anyio.open_file(path, "rb"),
        )

    service.download.side_effect = open_document
    app.dependency_overrides[get_current_user] = lambda: actor
    app.dependency_overrides[get_documents] = lambda: service
    started = anyio.Event()
    finish = anyio.Event()

    async def serve(slow: bool) -> None:
        """Keep the first response blocked at the network send boundary."""

        async def receive() -> dict[str, str]:
            """Keep both clients connected throughout their downloads."""
            await anyio.sleep_forever()
            return {"type": "http.disconnect"}

        async def send(message: dict[str, object]) -> None:
            """Simulate backpressure after the first body chunk."""
            if slow and message["type"] == "http.response.body" and message.get("body"):
                started.set()
                await finish.wait()

        await app(
            {
                "type": "http",
                "asgi": {"version": "3.0", "spec_version": "2.4"},
                "http_version": "1.1",
                "method": "GET",
                "scheme": "https",
                "path": "/lessons/1/files/1",
                "query_string": b"",
                "headers": [],
            },
            receive,
            send,
        )

    with anyio.fail_after(5):
        async with anyio.create_task_group() as tasks:
            tasks.start_soon(serve, True)
            await started.wait()
            tasks.start_soon(serve, False)
            await anyio.wait_all_tasks_blocked()
            assert service.download.await_count == 1
            assert slots.value == 0 and slots.statistics().tasks_waiting == 1
            finish.set()
    assert service.download.await_count == 2 and slots.value == 1
