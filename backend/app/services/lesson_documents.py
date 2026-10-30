"""Authorize document reservations, publish verified binaries and protect every download."""

from datetime import timedelta
from hashlib import file_digest
from os import fstat
from typing import BinaryIO
from uuid import uuid4

import anyio
from anyio import AsyncFile
from fastapi import Request
from sqlalchemy import delete, func, select
from sqlalchemy.exc import SQLAlchemyError

from app.core.documents import FILE_TYPES, DocumentSettings
from app.models.lessons import Lesson, LessonElement, LessonFile, LessonUpload
from app.schemas.lessons import LessonDetail, UploadCreate
from app.services.activity import record_event
from app.services.auth import UserContext
from app.services.document_storage import DocumentStorage
from app.services.errors import AuthError
from app.services.lessons import MAX_ELEMENTS, LessonService


class LessonDocumentService:
    """Keep long transfers outside course transactions and recheck rights before publication."""

    def __init__(self, lessons: LessonService, settings: DocumentSettings) -> None:
        """Reuse the request's authentication/database ownership and private storage settings."""
        self.lessons, self.settings = lessons, settings
        self.db = lessons.db
        self.storage = DocumentStorage(settings)

    async def target(self, lesson: Lesson, data: UploadCreate) -> LessonElement | None:
        """Validate parent ownership and distinguish a new resource from a file replacement."""
        elements = await self.lessons.repo.elements(lesson.id)
        parent = next((item for item in elements if item.id == data.parent_id), None)
        if parent is None or parent.kind not in {"section", "subsection", "table"}:
            raise AuthError(422, "Conteneur documentaire introuvable dans ce cours.")
        policy = self.lessons._element_values(
            "file", data, staff_only=self.lessons.section_staff(parent, elements)
        )
        data.schedule_mode = policy["schedule_mode"]
        data.starts_on, data.ends_on = policy["starts_on"], policy["ends_on"]
        self.lessons.validate_cell(parent, data.row_index, data.column_index)
        existing = next((item for item in elements if item.id == data.element_id), None)
        if data.element_id is not None:
            if (
                existing is None
                or existing.kind != "file"
                or existing.parent_id != parent.id
                or (existing.row_index, existing.column_index)
                != (data.row_index, data.column_index)
            ):
                raise AuthError(404, "Document à remplacer introuvable.")
        elif len(elements) >= MAX_ELEMENTS:
            raise AuthError(422, "Ce cours a atteint la limite de 500 éléments.")
        if parent.kind == "table" and any(
            item.parent_id == parent.id
            and item.row_index == data.row_index
            and item.column_index == data.column_index
            and item.id != data.element_id
            for item in elements
        ):
            raise AuthError(409, "La cellule contient déjà une ressource. Actualisez le tableau.")
        return existing

    async def reserve(
        self, actor: UserContext, lesson_id: int, data: UploadCreate
    ) -> dict[str, str]:
        """Reserve bounded quota under the existing lifecycle lock before accepting file bytes."""
        extension = data.filename.rsplit(".", 1)[-1].lower()
        if (
            extension not in FILE_TYPES
            or any(ord(char) < 32 for char in data.filename)
            or any(char in data.filename for char in ("/", "\\", ":"))
        ):
            raise AuthError(422, "Nom ou format de fichier non autorisé.")
        if data.size_bytes > FILE_TYPES[extension][0]:
            raise AuthError(413, "Le fichier dépasse la taille autorisée pour ce format.")
        if not data.title or data.body:
            raise AuthError(422, "Donnez un nom d’affichage au document.")
        await anyio.to_thread.run_sync(self.storage.prepare, data.size_bytes)
        async with self.db.begin():
            lesson = await self.lessons._write(actor, lesson_id, data.expected_version)
            await self.target(lesson, data)
            now = self.lessons.auth.clock()
            await self.db.execute(delete(LessonUpload).where(LessonUpload.expires_at <= now))
            reservations = list((await self.db.scalars(select(LessonUpload))).all())
            owned = [item for item in reservations if item.user_id == actor.id]
            if len(owned) >= 4 or len(reservations) >= 16:
                raise AuthError(
                    429, "Trop de transferts en cours. Réessayez dans quelques instants."
                )
            for predicate, reserved, quota in (
                (
                    LessonFile.lesson_id == lesson_id,
                    sum(item.size_bytes for item in reservations if item.lesson_id == lesson_id),
                    self.settings.course_quota_bytes,
                ),
                (
                    LessonFile.uploaded_by == actor.id,
                    sum(item.size_bytes for item in owned),
                    self.settings.user_quota_bytes,
                ),
                (
                    True,
                    sum(item.size_bytes for item in reservations),
                    self.settings.total_quota_bytes,
                ),
            ):
                used = await self.db.scalar(
                    select(func.coalesce(func.sum(LessonFile.size_bytes), 0)).where(predicate)
                )
                if used + reserved + data.size_bytes > quota:
                    raise AuthError(413, "Le quota documentaire est atteint.")
            key = uuid4().hex
            self.db.add(
                LessonUpload(
                    id=key,
                    lesson_id=lesson_id,
                    user_id=actor.id,
                    size_bytes=data.size_bytes,
                    payload=data.model_dump(mode="json"),
                    expires_at=now + timedelta(minutes=10),
                )
            )
            return {"upload_id": key}

    async def cancel(self, actor: UserContext, lesson_id: int, key: str) -> None:
        """Release an actor-owned reservation; active transfers handle their own cleanup."""
        async with self.db.begin():
            await self.lessons._principal(actor)
            await self.db.execute(
                delete(LessonUpload).where(
                    LessonUpload.id == key,
                    LessonUpload.user_id == actor.id,
                    LessonUpload.lesson_id == lesson_id,
                    LessonUpload.started_at.is_(None),
                )
            )

    async def receive(
        self, actor: UserContext, lesson_id: int, key: str, request: Request
    ) -> LessonDetail:
        """Publish a single-use upload after rechecking version and access following validation."""
        async with self.db.begin():
            upload = await self.db.scalar(
                select(LessonUpload).where(LessonUpload.id == key).with_for_update()
            )
            if upload is None or upload.user_id != actor.id or upload.lesson_id != lesson_id:
                raise AuthError(404, "Dépôt introuvable.")
            if upload.started_at is not None or upload.expires_at <= self.lessons.auth.clock():
                raise AuthError(409, "Ce dépôt a déjà commencé ou a expiré.")
            data = UploadCreate.model_validate(upload.payload)
            lesson = await self.lessons._write(actor, lesson_id, data.expected_version)
            await self.target(lesson, data)
            upload.started_at = self.lessons.auth.clock()
        committed = False
        try:
            digest = await self.storage.receive(key, request.stream(), data.size_bytes)
            extension = data.filename.rsplit(".", 1)[-1].lower()
            mime = await self.storage.validate(key, extension)
            await anyio.to_thread.run_sync(self.storage.publish, key)
            async with self.db.begin():
                lesson = await self.lessons._write(actor, lesson_id, data.expected_version)
                existing = await self.target(lesson, data)
                parent = await self.db.get(LessonElement, data.parent_id)
                if existing is None:
                    siblings = [
                        item.position
                        for item in await self.lessons.repo.elements(lesson_id)
                        if item.parent_id == parent.id
                    ]
                    existing = LessonElement(
                        lesson_id=lesson_id,
                        parent_id=parent.id,
                        kind="file",
                        position=max(siblings, default=-1) + 1,
                        row_index=data.row_index,
                        column_index=data.column_index,
                        **self.lessons._element_values("file", data),
                    )
                    self.db.add(existing)
                    await self.db.flush()
                else:
                    await self.db.execute(
                        delete(LessonFile).where(LessonFile.element_id == existing.id)
                    )
                    for name, value in self.lessons._element_values("file", data).items():
                        setattr(existing, name, value)
                self.db.add(
                    LessonFile(
                        lesson_id=lesson_id,
                        element_id=existing.id,
                        uploaded_by=actor.id,
                        storage_key=key,
                        original_name=data.filename,
                        extension=extension,
                        media_type=mime,
                        size_bytes=data.size_bytes,
                        sha256=digest,
                    )
                )
                await self.db.execute(delete(LessonUpload).where(LessonUpload.id == key))
                await self.lessons._changed(lesson)
                await self.lessons._event(
                    actor,
                    lesson,
                    "element_updated" if data.element_id else "element_created",
                    element_id=existing.id,
                    element_kind="file",
                    element_title=existing.title,
                )
                result = await self.lessons._detail(actor, lesson)
            committed = True
            return result
        except TimeoutError:
            raise AuthError(408, "Le transfert ou la validation a pris trop de temps.") from None
        except OSError:
            raise AuthError(503, "Le stockage documentaire est indisponible.") from None
        finally:
            # Shield rollback cleanup from disconnects; reconciliation covers process crashes.
            with anyio.CancelScope(shield=True):
                try:
                    async with self.db.begin():
                        await self.db.execute(
                            delete(LessonUpload).where(
                                LessonUpload.id == key, LessonUpload.user_id == actor.id
                            )
                        )
                    self.storage.remove(key, temporary=True)
                    if not committed:
                        async with self.db.begin():
                            published = await self.db.scalar(
                                select(LessonFile.id).where(LessonFile.storage_key == key)
                            )
                        if published is None:
                            self.storage.remove(key)
                except (OSError, ValueError, SQLAlchemyError):
                    pass

    async def download(
        self, actor: UserContext, lesson_id: int, file_id: int
    ) -> tuple[LessonFile, AsyncFile[bytes]]:
        """Authorize current visibility and open the immutable file before returning its stream."""
        async with self.db.begin():
            lesson = await self.lessons._lesson(lesson_id)
            visible = await self.lessons._detail(actor, lesson)
            if not any(
                item.file is not None
                and item.file.id == file_id
                and (visible.staff_view or item.available)
                for item in visible.elements
            ):
                raise AuthError(404, "Document introuvable.")
            file = await self.db.get(LessonFile, file_id)
            source = None
            try:
                source = await anyio.open_file(self.storage.path(file.storage_key), "rb")
                if fstat(source.wrapped.fileno()).st_size != file.size_bytes:
                    raise AuthError(503, "Document indisponible : contrôle d’intégrité en échec.")

                def fingerprint(stream: BinaryIO) -> str:
                    """Check original bytes before sending any potentially corrupted content."""
                    digest = file_digest(stream, "sha256").hexdigest()
                    stream.seek(0)
                    return digest

                if await anyio.to_thread.run_sync(fingerprint, source.wrapped) != file.sha256:
                    raise AuthError(503, "Document indisponible : contrôle d’intégrité en échec.")
            except (OSError, ValueError):
                if source is not None:
                    await source.aclose()
                raise AuthError(503, "Document temporairement indisponible.") from None
            except BaseException:
                if source is not None:
                    with anyio.CancelScope(shield=True):
                        await source.aclose()
                raise
            return file, source

    async def record_download(self, actor: UserContext, file: LessonFile) -> None:
        """Record a completed server transfer after streaming, in a short separate transaction.

        Parameters
        ----------
        actor
            Previously authenticated recipient of this transfer.
        file
            Immutable file facts captured before streaming; deletion does not erase history.
        """
        async with self.db.begin():
            element = await self.db.get(LessonElement, file.element_id)
            await record_event(
                self.db,
                "lesson.file_downloaded",
                actor.id,
                subject_user_id=actor.id,
                resource_type="lesson",
                resource_id=file.lesson_id,
                data={
                    "file_id": file.id,
                    "size_bytes": file.size_bytes,
                    "document_title": element.title if element is not None else None,
                },
                occurred_at=self.lessons.auth.clock(),
            )
