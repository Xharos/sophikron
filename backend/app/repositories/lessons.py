"""SQL-only course queries; business authorization belongs to the lesson service."""

from datetime import date

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Promotion, UserPromotion
from app.models.lessons import Lesson, LessonCollaborator, LessonElement, LessonPromotion


class LessonRepository:
    """Share the request transaction and keep course predicates reusable."""

    def __init__(self, db: AsyncSession) -> None:
        """Bind the session without starting an implicit business transaction."""
        self.db = db

    async def lesson(self, lesson_id: int, *, lock: bool = False) -> Lesson | None:
        """Read a fresh page and optionally serialize all of its mutations."""
        query = (
            select(Lesson).where(Lesson.id == lesson_id).execution_options(populate_existing=True)
        )
        if lock:
            query = query.with_for_update()
        return await self.db.scalar(query)

    async def elements(self, lesson_id: int) -> list[LessonElement]:
        """Load the shallow content tree in stable sibling order."""
        return list(
            (
                await self.db.scalars(
                    select(LessonElement)
                    .where(LessonElement.lesson_id == lesson_id)
                    .order_by(LessonElement.position, LessonElement.id)
                )
            ).all()
        )

    def accessible(self, user_id: int, today: date) -> Select[tuple[int]]:
        """Select pages granted by a current membership, active promotion and valid period."""
        return (
            select(LessonPromotion.lesson_id)
            .join(Promotion, Promotion.id == LessonPromotion.promotion_id)
            .join(UserPromotion, UserPromotion.promotion_id == Promotion.id)
            .where(
                UserPromotion.user_id == user_id,
                Promotion.is_active,
                LessonPromotion.starts_on <= today,
                LessonPromotion.ends_on >= today,
            )
        )

    async def collaborator(self, lesson_id: int, user_id: int) -> bool:
        """Check only the association; the caller must also check current teacher grants."""
        return await self.db.get(LessonCollaborator, (lesson_id, user_id)) is not None
