"""Queries used by the quiz editor, learner passage and course statistics."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from app.models.lesson_quiz import LessonQuizPassage, LessonQuizVersion
from app.models.quiz import QuizQuestion


class LessonQuizRepository:
    """Use the caller's transaction for all snapshots and progression."""

    def __init__(self, db: AsyncSession) -> None:
        """Bind the request-owned connection."""
        self.db = db

    async def latest(self, element_ids: list[int]) -> dict[int, LessonQuizVersion]:
        """Load latest lightweight metadata per requested block."""
        rows = await self.db.scalars(
            select(LessonQuizVersion)
            .where(LessonQuizVersion.element_id.in_(element_ids))
            .distinct(LessonQuizVersion.element_id)
            .order_by(LessonQuizVersion.element_id, LessonQuizVersion.id.desc())
        )
        return {row.element_id: row for row in rows}

    async def version(self, version_id: int) -> LessonQuizVersion:
        """Load a passage's frozen content on demand."""
        return (
            await self.db.scalars(
                select(LessonQuizVersion)
                .where(LessonQuizVersion.id == version_id)
                .options(undefer(LessonQuizVersion.cards))
            )
        ).one()

    async def card(self, version_id: int, index: int) -> dict | None:
        """Fetch only the requested card, including its image when present."""
        return await self.db.scalar(
            select(LessonQuizVersion.cards[index]).where(LessonQuizVersion.id == version_id)
        )

    async def passage(self, element_id: int, user_id: int) -> LessonQuizPassage | None:
        """Return the first passage under an already serialized learner operation."""
        return await self.db.get(LessonQuizPassage, (element_id, user_id))

    async def for_user(self, element_ids: list[int], user_id: int) -> dict[int, LessonQuizPassage]:
        """Batch progress summaries for the current course reader."""
        rows = await self.db.scalars(
            select(LessonQuizPassage).where(
                LessonQuizPassage.element_id.in_(element_ids), LessonQuizPassage.user_id == user_id
            )
        )
        return {row.element_id: row for row in rows}

    async def bank(self, subject_id: int, term: str) -> list[dict]:
        """Search only active sheets and return their labels without answer keys."""
        rows = await self.db.execute(
            select(QuizQuestion.id, QuizQuestion.title)
            .where(
                QuizQuestion.subject_id == subject_id,
                ~QuizQuestion.archived,
                QuizQuestion.title.icontains(term, autoescape=True),
            )
            .order_by(QuizQuestion.title, QuizQuestion.id)
            .limit(50)
        )
        return [dict(row) for row in rows.mappings()]

    async def bank_cards(self, subject_id: int, ids: list[int]) -> dict[int, QuizQuestion]:
        """Fetch currently selectable cards of the course subject."""
        rows = await self.db.scalars(
            select(QuizQuestion).where(
                QuizQuestion.subject_id == subject_id,
                ~QuizQuestion.archived,
                QuizQuestion.id.in_(ids),
            )
        )
        return {row.id: row for row in rows}
