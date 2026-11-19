"""Enforce question bank permissions and correct stateless preview answers."""

from base64 import b64decode, b64encode
from binascii import Error as Base64Error
from io import BytesIO

from anyio import to_thread
from PIL import Image, ImageOps

from app.models.quiz import QuizQuestion
from app.models.site import Subject
from app.repositories.quiz import QuizRepository
from app.schemas.quiz import (
    MAX_IMAGE_BYTES,
    ChoiceRule,
    NumberRule,
    QuestionFields,
    Rule,
    TextRule,
    normalize_answer,
    parse_number,
)
from app.services.activity import record_event
from app.services.auth import AuthService, UserContext
from app.services.course_rights import has_subject
from app.services.errors import FORBIDDEN, AuthError


def prepare_image(value: str) -> str:
    """Decode and re-encode a single bounded raster image, stripping metadata."""
    header, _, encoded = value.partition(",")
    formats = {"data:image/jpeg;base64": "JPEG", "data:image/png;base64": "PNG"}
    if header not in formats:
        raise AuthError(422, "Image : seuls les formats PNG et JPEG sont acceptés.")
    image_format = formats[header]
    try:
        content = b64decode(encoded, validate=True)
        if len(content) > MAX_IMAGE_BYTES:
            raise AuthError(422, "Image : le fichier dépasse 1 Mio.")
        with Image.open(BytesIO(content), formats=[image_format]) as image:
            if image.width * image.height > 4_000_000:
                raise AuthError(422, "Image : la résolution dépasse 4 mégapixels.")
            if getattr(image, "n_frames", 1) != 1:
                raise AuthError(422, "Image : utilisez une image fixe.")
            mode = "RGBA" if image.has_transparency_data and image_format == "PNG" else "RGB"
            clean = ImageOps.exif_transpose(image).convert(mode)
            clean.info.clear()
            with BytesIO() as output:
                clean.save(output, format=image_format, optimize=True)
                if output.tell() > MAX_IMAGE_BYTES:
                    raise AuthError(
                        422, "Image : après traitement, elle dépasse 1 Mio. Réduisez-la."
                    )
                return f"{header},{b64encode(output.getvalue()).decode('ascii')}"
    except Image.DecompressionBombError:
        raise AuthError(422, "Image : la résolution dépasse 4 mégapixels.") from None
    except (Base64Error, ValueError, SyntaxError, OSError, EOFError):
        raise AuthError(
            422,
            "Image : le fichier est illisible ou son format réel ne correspond pas à PNG ou JPEG.",
        ) from None


def answer_matches(rule: Rule, answer: str | list[int]) -> bool:
    """Compare a submitted answer with the expected value or exact option set."""
    if isinstance(rule, ChoiceRule):
        if not isinstance(answer, list):
            raise AuthError(422, "Sélectionnez une ou plusieurs propositions.")
        if max(answer, default=-1) >= len(rule.options) or len(answer) != len(set(answer)):
            raise AuthError(422, "Sélection invalide.")
        return set(answer) == set(rule.correct)
    if not isinstance(answer, str):
        raise AuthError(422, "Saisissez une réponse.")
    if isinstance(rule, NumberRule):
        try:
            actual = parse_number(answer)
        except ValueError as error:
            raise AuthError(422, str(error)) from None
        return abs(actual - parse_number(rule.expected)) <= parse_number(rule.tolerance)
    return normalize_answer(answer) in {normalize_answer(value) for value in rule.accepted}


class QuizService:
    """Apply live subject permissions before writing shared question data."""

    def __init__(self, auth: AuthService) -> None:
        """Reuse the request's session and authentication service."""
        self.auth, self.db = auth, auth.db
        self.repo = QuizRepository(self.db)

    async def catalog(self) -> list[dict]:
        """Return statistics for every subject, including unassigned subjects."""
        return await self.repo.catalog()

    async def can_edit(self, actor: UserContext, subject_id: int, roles: set[str]) -> bool:
        """Allow administrators and teachers currently assigned to an active subject."""
        return "admin" in roles or (
            "teacher" in roles and await has_subject(self.db, actor.id, subject_id)
        )

    async def subject(self, actor: UserContext, subject_id: int) -> dict:
        """Return subject identity, summary rows and UI editing capabilities."""
        subject = await self.db.get(Subject, subject_id)
        if subject is None:
            raise AuthError(404, "Matière introuvable.")
        editable = await self.can_edit(actor, subject_id, set(actor.roles))
        return {
            "id": subject.id,
            "name": subject.name,
            "icon": subject.icon,
            "color": subject.color,
            "can_edit": editable,
            "questions": await self.repo.summaries(subject_id),
            "competencies": await self.repo.competencies(subject_id) if editable else [],
        }

    async def _require_edit(self, actor: UserContext, subject_id: int) -> Subject:
        """Serialize writes with role and assignment changes and recheck authority."""
        await self.auth._lifecycle_lock()
        await self.auth._actor(actor)
        roles = set(await self.auth.repo.roles(actor.id))
        if not await self.can_edit(actor, subject_id, roles):
            raise AuthError(403, FORBIDDEN)
        subject = await self.db.get(Subject, subject_id)
        if subject is None:
            raise AuthError(404, "Matière introuvable.")

        return subject

    async def _event(
        self, actor: UserContext, subject: Subject, row: QuizQuestion, action: str
    ) -> None:
        """Record the actor, title and subject in the same transaction as the change."""
        await record_event(
            self.db,
            f"quiz.{action}",
            actor.id,
            resource_type="quiz_question",
            resource_id=row.id,
            data={"title": row.title, "subject_name": subject.name},
        )

    async def _question(
        self, subject_id: int, question_id: int, version: int | None = None
    ) -> QuizQuestion:
        """Resolve a question and check an optional optimistic revision."""
        question = await self.repo.question(subject_id, question_id)
        if question is None:
            raise AuthError(404, "Fiche introuvable.")
        if version is not None and version != question.version:
            raise AuthError(409, "La fiche a changé. Rechargez-la avant de continuer.")
        return question

    async def detail(
        self, actor: UserContext, subject_id: int, question_id: int, *, edit: bool
    ) -> dict:
        """Send the correction rule only to an authorized editor who requests it."""
        if edit and not await self.can_edit(actor, subject_id, set(actor.roles)):
            raise AuthError(403, FORBIDDEN)
        row = await self._question(subject_id, question_id)
        detail = {
            "id": row.id,
            "title": row.title,
            "prompt": row.prompt,
            "statement": row.statement,
            "kind": row.kind,
            "image": row.image,
            "image_alt": row.image_alt,
            "archived": row.archived,
            "version": row.version,
            "options": row.rule.get("options", []),
        }
        if edit:
            detail["rule"] = row.rule
            detail["competency_ids"] = await self.repo.linked_competencies(row.id)
        return detail

    async def save(
        self,
        actor: UserContext,
        subject_id: int,
        data: QuestionFields,
        question_id: int | None = None,
        version: int | None = None,
    ) -> dict:
        """Atomically save a definition, its image and optional competency links."""
        subject = await self._require_edit(actor, subject_id)
        if question_id is None:
            row = QuizQuestion(subject_id=subject_id)
        else:
            row = await self._question(subject_id, question_id, version)
        if data.competency_ids and (
            await self.repo.lock_competencies(subject_id, data.competency_ids)
            != set(data.competency_ids)
        ):
            raise AuthError(422, "Choisissez des compétences existantes de cette matière.")
        if data.image != row.image:
            row.image = await to_thread.run_sync(prepare_image, data.image) if data.image else None
        row.image_alt = data.image_alt if row.image else ""
        row.title, row.prompt = data.title, data.prompt
        row.statement = data.statement
        row.kind, row.rule = data.rule.kind, data.rule.model_dump()
        if question_id is None:
            self.db.add(row)
        else:
            row.version += 1
        await self.db.flush()
        await self.repo.replace_competencies(row.id, data.competency_ids)
        await self._event(actor, subject, row, "created" if question_id is None else "updated")
        await self.db.commit()
        return {"id": row.id}

    async def archive(
        self, actor: UserContext, subject_id: int, question_id: int, version: int, archived: bool
    ) -> None:
        """Change availability without rewriting the definition."""
        subject = await self._require_edit(actor, subject_id)
        row = await self._question(subject_id, question_id, version)
        row.archived = archived
        row.version += 1
        await self._event(actor, subject, row, "archived" if archived else "restored")
        await self.db.commit()

    async def remove(
        self, actor: UserContext, subject_id: int, question_id: int, version: int
    ) -> None:
        """Delete a question and its competency links in one transaction."""
        subject = await self._require_edit(actor, subject_id)
        row = await self._question(subject_id, question_id, version)
        await self._event(actor, subject, row, "deleted")
        await self.db.delete(row)
        await self.db.commit()

    async def preview(
        self, subject_id: int, question_id: int, version: int, answer: str | list[int]
    ) -> dict[str, bool]:
        """Return correctness for the displayed revision without saving an attempt."""
        row = await self._question(subject_id, question_id, version)
        rules = {"choice": ChoiceRule, "number": NumberRule, "text": TextRule}
        return {"correct": answer_matches(rules[row.kind].model_validate(row.rule), answer)}
