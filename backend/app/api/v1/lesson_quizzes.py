"""Course-scoped authoring, practice and first-passage reports."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query

from app.dependencies.auth import AuthenticatedUser, AuthServiceDependency
from app.schemas.lesson_quizzes import QuizAnswer, QuizReference, QuizReplay, QuizRun, QuizStart
from app.services.lesson_quizzes import LessonQuizService

router = APIRouter(prefix="/lessons", tags=["Course quizzes"])
Identifier = Annotated[int, Path(gt=0, le=2**63 - 1)]


def quiz_service(auth: AuthServiceDependency) -> LessonQuizService:
    """Build a course quiz service for the authenticated request."""
    return LessonQuizService(auth)


Service = Annotated[LessonQuizService, Depends(quiz_service)]


@router.get("/{lesson_id}/quiz-options", response_model=list[QuizReference])
async def options(
    lesson_id: Identifier,
    actor: AuthenticatedUser,
    service: Service,
    q: Annotated[str, Query(max_length=160)] = "",
) -> list[dict]:
    """Search active bank cards in the course subject as an editor."""
    return await service.options(actor, lesson_id, q)


@router.post("/{lesson_id}/quizzes/{element_id}/start")
async def start(
    lesson_id: Identifier,
    element_id: Identifier,
    data: QuizStart,
    actor: AuthenticatedUser,
    service: Service,
) -> QuizRun:
    """Start, resume or replay the block while its availability permits it."""
    return await service.start(actor, lesson_id, element_id, data)


@router.post("/{lesson_id}/quizzes/{element_id}/answer")
async def answer(
    lesson_id: Identifier,
    element_id: Identifier,
    data: QuizAnswer,
    actor: AuthenticatedUser,
    service: Service,
) -> QuizRun:
    """Evaluate and record a first-passage answer once."""
    return await service.answer(actor, lesson_id, element_id, data)


@router.post("/{lesson_id}/quizzes/{element_id}/replay")
async def replay(
    lesson_id: Identifier,
    element_id: Identifier,
    data: QuizReplay,
    actor: AuthenticatedUser,
    service: Service,
) -> dict:
    """Read and evaluate replay cards without keeping a second passage."""
    return await service.replay(actor, lesson_id, element_id, data)


@router.get("/{lesson_id}/quizzes/{element_id}/results")
async def results(
    lesson_id: Identifier,
    element_id: Identifier,
    actor: AuthenticatedUser,
    service: Service,
) -> dict:
    """List expected pupils and the counters from their first passages."""
    return await service.results(actor, lesson_id, element_id)
