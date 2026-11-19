"""Authenticated teacher and administrator access to the question bank."""

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute

from app.dependencies.auth import AuthServiceDependency, RequireRole
from app.schemas.quiz import ArchiveUpdate, PreviewAnswer, QuestionFields, QuestionUpdate, Revision
from app.services.auth import UserContext
from app.services.errors import AuthError
from app.services.quiz import QuizService

FIELD_LABELS = {
    "title": "Titre",
    "statement": "Énoncé",
    "prompt": "Question",
    "rule": "Type de réponse",
    "expected": "Valeur attendue",
    "tolerance": "Tolérance",
    "options": "Propositions",
    "correct": "Bonnes réponses",
    "accepted": "Réponses acceptées",
    "image": "Image",
    "image_alt": "Description de l’image",
    "competency_ids": "Compétences",
    "answer": "Réponse",
    "version": "Version de la fiche",
}


class QuizRoute(APIRoute):
    """Expose Quiz field errors using trusted labels and validator messages."""

    def get_route_handler(self) -> Callable[[Request], Awaitable[Response]]:
        """Wrap FastAPI's handler without disclosing rejected values."""
        handler = super().get_route_handler()

        async def validate(request: Request) -> Response:
            """Render a concise validation error for each invalid field."""
            try:
                return await handler(request)
            except RequestValidationError as error:
                messages = []
                for issue in error.errors()[:5]:
                    location = issue["loc"]
                    field = next(
                        (part for part in reversed(location) if part in FIELD_LABELS), None
                    )
                    code = issue["type"]
                    if code == "value_error" and isinstance(
                        detail := issue.get("ctx", {}).get("error"), ValueError
                    ):
                        message = str(detail)
                    elif field == "image" and code == "string_too_long":
                        message = "Image : le fichier dépasse 1 Mio."
                    elif field:
                        label = FIELD_LABELS[field]
                        limit = issue.get("ctx", {})
                        if code in {"missing", "string_too_short"}:
                            message = f"{label} : champ obligatoire."
                        elif code == "string_too_long":
                            message = f"{label} : {limit['max_length']} caractères maximum."
                        elif code == "too_long":
                            message = f"{label} : {limit['max_length']} éléments maximum."
                        elif code == "too_short":
                            message = f"{label} : {limit['min_length']} éléments minimum."
                        else:
                            message = f"{label} : valeur invalide."
                    else:
                        message = "La structure de la demande Quiz est invalide."
                    if message not in messages:
                        messages.append(message)
                raise AuthError(422, " ".join(messages)) from None

        return validate


router = APIRouter(prefix="/quiz", tags=["Quiz"], route_class=QuizRoute)
QuizActor = Annotated[UserContext, Depends(RequireRole("admin", "teacher"))]
Identifier = Annotated[int, Path(gt=0, le=2**63 - 1)]


def get_service(auth: AuthServiceDependency) -> QuizService:
    """Construct the question bank service with request resources."""
    return QuizService(auth)


Service = Annotated[QuizService, Depends(get_service)]


@router.get("")
async def catalog(actor: QuizActor, service: Service) -> list[dict]:
    """List question counts per subject."""
    return await service.catalog()


@router.get("/subjects/{subject_id}")
async def subject(subject_id: Identifier, actor: QuizActor, service: Service) -> dict:
    """List question summaries for a single subject."""
    return await service.subject(actor, subject_id)


@router.get("/subjects/{subject_id}/questions/{question_id}")
async def detail(
    subject_id: Identifier,
    question_id: Identifier,
    actor: QuizActor,
    service: Service,
    edit: bool = False,
) -> dict:
    """Read a pupil-style preview or request authorized editor fields."""
    return await service.detail(actor, subject_id, question_id, edit=edit)


@router.post("/subjects/{subject_id}/questions", status_code=201)
async def create(
    subject_id: Identifier, data: QuestionFields, actor: QuizActor, service: Service
) -> dict:
    """Create a standalone question."""
    return await service.save(actor, subject_id, data)


@router.put("/subjects/{subject_id}/questions/{question_id}")
async def update(
    subject_id: Identifier,
    question_id: Identifier,
    data: QuestionUpdate,
    actor: QuizActor,
    service: Service,
) -> dict:
    """Replace the definition of an existing question."""
    return await service.save(actor, subject_id, data, question_id, data.version)


@router.patch("/subjects/{subject_id}/questions/{question_id}", status_code=204)
async def archive(
    subject_id: Identifier,
    question_id: Identifier,
    data: ArchiveUpdate,
    actor: QuizActor,
    service: Service,
) -> None:
    """Set the question's archive status."""
    await service.archive(actor, subject_id, question_id, data.version, data.archived)


@router.delete("/subjects/{subject_id}/questions/{question_id}", status_code=204)
async def remove(
    subject_id: Identifier,
    question_id: Identifier,
    data: Revision,
    actor: QuizActor,
    service: Service,
) -> None:
    """Permanently remove a question."""
    await service.remove(actor, subject_id, question_id, data.version)


@router.post("/subjects/{subject_id}/questions/{question_id}/preview")
async def preview(
    subject_id: Identifier,
    question_id: Identifier,
    data: PreviewAnswer,
    actor: QuizActor,
    service: Service,
) -> dict[str, bool]:
    """Correct a staff preview without recording attempts."""
    return await service.preview(subject_id, question_id, data.version, data.answer)
