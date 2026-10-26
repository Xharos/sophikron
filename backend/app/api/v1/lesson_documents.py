"""Private binary course transfers; arbitrary paths and original names never address storage."""

import logging
import re
from collections.abc import AsyncIterator
from typing import Annotated
from urllib.parse import quote

import anyio
from fastapi import APIRouter, Depends, HTTPException, Path, Request, Response
from sqlalchemy.exc import SQLAlchemyError
from starlette.responses import StreamingResponse

from app.api.v1.lessons import Identifier, Service
from app.core.documents import FILE_TYPES
from app.dependencies.auth import AuthenticatedUser
from app.schemas.lessons import LessonDetail, UploadCreate
from app.services.lesson_documents import LessonDocumentService

router = APIRouter(prefix="/lessons", tags=["Course documents"])
UploadKey = Annotated[str, Path(pattern=r"^[0-9a-f]{32}$")]


def get_documents(request: Request, lessons: Service) -> LessonDocumentService:
    """Bind document operations to this request's authenticated course service."""
    return LessonDocumentService(lessons, request.app.state.document_settings)


Documents = Annotated[LessonDocumentService, Depends(get_documents)]


async def download_slot(request: Request, actor: AuthenticatedUser) -> AsyncIterator[None]:
    """Queue authenticated downloads globally and hold capacity until the response finishes.

    Parameters
    ----------
    request
        Request owning the application-wide FIFO semaphore and disconnect channel.
    actor
        Authenticated principal; the service rechecks live access after waiting.

    Yields
    ------
    None
        Permission to prepare and stream one download, without a per-account limit.
    """
    slots = request.app.state.document_download_slots
    acquired = False
    disconnected = False
    try:
        async with anyio.create_task_group() as tasks:

            async def watch_disconnect() -> None:
                """Remove abandoned waiters without opening files or transactions."""
                nonlocal disconnected
                while True:
                    if (await request.receive())["type"] == "http.disconnect":
                        disconnected = True
                        tasks.cancel_scope.cancel()
                        return

            tasks.start_soon(watch_disconnect)
            await slots.acquire()
            acquired = True
            tasks.cancel_scope.cancel()
        if disconnected:
            raise HTTPException(status_code=499, detail="Téléchargement annulé.")
        yield
    finally:
        if acquired:
            slots.release()


@router.get("/document-limits")
async def limits(actor: AuthenticatedUser) -> dict[str, object]:
    """Expose the single source of format/size limits before the browser sends file bytes."""
    return {"types": {extension: facts[0] for extension, facts in FILE_TYPES.items()}}


@router.post("/{lesson_id}/uploads", status_code=201)
async def reserve(
    lesson_id: Identifier, data: UploadCreate, actor: AuthenticatedUser, service: Documents
) -> dict[str, str]:
    """Authorize metadata and reserve quota before the large binary request."""
    return await service.reserve(actor, lesson_id, data)


@router.put("/{lesson_id}/uploads/{key}", response_model=LessonDetail)
async def upload(
    lesson_id: Identifier,
    key: UploadKey,
    request: Request,
    actor: AuthenticatedUser,
    service: Documents,
) -> LessonDetail:
    """Stream the raw body through structural validation and transactional publication."""
    return await service.receive(actor, lesson_id, key, request)


@router.delete("/{lesson_id}/uploads/{key}", status_code=204)
async def cancel(
    lesson_id: Identifier, key: UploadKey, actor: AuthenticatedUser, service: Documents
) -> Response:
    """Release an actor-owned reservation after selecting another file or closing the editor."""
    await service.cancel(actor, lesson_id, key)
    return Response(status_code=204)


@router.get(
    "/{lesson_id}/files/{file_id}",
    dependencies=[Depends(download_slot, scope="request")],
)
async def download(
    lesson_id: Identifier, file_id: Identifier, actor: AuthenticatedUser, service: Documents
) -> StreamingResponse:
    """Stream an authorized attachment with a safe Unicode download name and no caching."""
    file, source = await service.download(actor, lesson_id, file_id)

    async def content() -> AsyncIterator[bytes]:
        """Close the open private file on completion, cancellation or downstream disconnect."""
        sent = 0
        try:
            while chunk := await source.read(65536):
                sent += len(chunk)
                yield chunk
            # Reached only after every chunk was sent; cancellation never records a completion.
            with anyio.CancelScope(shield=True):
                try:
                    if sent == file.size_bytes:
                        await service.record_download(actor, file)
                except SQLAlchemyError:
                    logging.getLogger(__name__).warning("Download statistics unavailable")
        finally:
            with anyio.CancelScope(shield=True):
                await source.aclose()

    fallback = re.sub(r"[^A-Za-z0-9_. -]", "_", file.original_name)[:200]
    return StreamingResponse(
        content(),
        media_type=file.media_type,
        headers={
            "Content-Disposition": (
                f'attachment; filename="{fallback}"; '
                f"filename*=UTF-8''{quote(file.original_name, safe='')}"
            ),
            "Content-Length": str(file.size_bytes),
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "X-Robots-Tag": "noindex, nofollow",
        },
    )
