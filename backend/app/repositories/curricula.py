"""Database reads for programme catalogues and subject-scoped graphs."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.curricula import Competency, CompetencyLink, Curriculum


class CurriculaRepository:
    """Keep graph queries separate from permissions and transaction ownership."""

    def __init__(self, db: AsyncSession) -> None:
        """Bind the request's database session."""
        self.db = db

    async def curriculum(self, identifier: int, *, lock: bool = False) -> Curriculum | None:
        """Read a programme, optionally serializing its graph edits."""
        statement = select(Curriculum).where(Curriculum.id == identifier)
        return await self.db.scalar(statement.with_for_update() if lock else statement)

    async def nodes(self, curriculum_id: int, subject_id: int) -> list[Competency]:
        """Read one subject's graph in stable sibling order."""
        return list(
            await self.db.scalars(
                select(Competency)
                .where(
                    Competency.curriculum_id == curriculum_id, Competency.subject_id == subject_id
                )
                .order_by(Competency.position, Competency.id)
            )
        )

    async def edges(self, curriculum_id: int, subject_id: int) -> list[tuple[int, int]]:
        """Read parent-child pairs without expanding shared nodes into copies."""
        return [
            (parent, child)
            for parent, child in await self.db.execute(
                select(CompetencyLink.parent_id, CompetencyLink.child_id)
                .where(
                    CompetencyLink.curriculum_id == curriculum_id,
                    CompetencyLink.subject_id == subject_id,
                )
                .order_by(CompetencyLink.parent_id, CompetencyLink.child_id)
            )
        ]
