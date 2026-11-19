"""Queries for the subject catalogue, questions and competency associations."""

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.curricula import Competency, Curriculum
from app.models.quiz import QuizQuestion, QuizQuestionCompetency
from app.models.site import Subject


class QuizRepository:
    """Read summaries without fetching images or correction rules."""

    def __init__(self, db: AsyncSession) -> None:
        """Use the request's database transaction."""
        self.db = db

    async def catalog(self) -> list[dict]:
        """Count visible and archived questions, including empty subjects."""
        total = func.count(QuizQuestion.id)
        archived = total.filter(QuizQuestion.archived)
        rows = await self.db.execute(
            select(Subject, total, archived)
            .outerjoin(QuizQuestion, QuizQuestion.subject_id == Subject.id)
            .group_by(Subject.id)
            .order_by(Subject.name_key)
        )
        return [
            {
                "id": subject.id,
                "name": subject.name,
                "icon": subject.icon,
                "color": subject.color,
                "is_active": subject.is_active,
                "total": count,
                "archived": archived_count,
            }
            for subject, count, archived_count in rows
        ]

    async def summaries(self, subject_id: int) -> list[dict]:
        """Return table columns only, ordered by title and identity."""
        rows = await self.db.execute(
            select(QuizQuestion.id, QuizQuestion.title, QuizQuestion.archived, QuizQuestion.version)
            .where(QuizQuestion.subject_id == subject_id)
            .order_by(QuizQuestion.title, QuizQuestion.id)
        )
        return [dict(row) for row in rows.mappings()]

    async def question(self, subject_id: int, question_id: int) -> QuizQuestion | None:
        """Load a question only under its owning subject."""
        return await self.db.scalar(
            select(QuizQuestion).where(
                QuizQuestion.id == question_id, QuizQuestion.subject_id == subject_id
            )
        )

    async def competencies(self, subject_id: int) -> list[dict]:
        """List selectable competencies with their programme names."""
        rows = await self.db.execute(
            select(Competency.id, Competency.name, Curriculum.title.label("curriculum"))
            .join(Curriculum, Curriculum.id == Competency.curriculum_id)
            .where(Competency.subject_id == subject_id)
            .order_by(Curriculum.title, Competency.name, Competency.id)
        )
        return [dict(row) for row in rows.mappings()]

    async def linked_competencies(self, question_id: int) -> list[int]:
        """Return the question's current competency IDs."""
        return list(
            await self.db.scalars(
                select(QuizQuestionCompetency.competency_id)
                .where(QuizQuestionCompetency.question_id == question_id)
                .order_by(QuizQuestionCompetency.competency_id)
            )
        )

    async def lock_competencies(self, subject_id: int, ids: list[int]) -> set[int]:
        """Hold selected competencies against concurrent removal until commit."""
        return set(
            await self.db.scalars(
                select(Competency.id)
                .where(Competency.subject_id == subject_id, Competency.id.in_(ids))
                .order_by(Competency.id)
                .with_for_update(read=True, key_share=True)
            )
        )

    async def replace_competencies(self, question_id: int, ids: list[int]) -> None:
        """Replace links within the same transaction as the definition."""
        await self.db.execute(
            delete(QuizQuestionCompetency).where(QuizQuestionCompetency.question_id == question_id)
        )
        self.db.add_all(
            [QuizQuestionCompetency(question_id=question_id, competency_id=key) for key in ids]
        )
