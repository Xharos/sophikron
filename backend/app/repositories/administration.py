"""Parameterized dashboard queries without transaction or authorization ownership."""

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Promotion, Role, User, UserPromotion, UserRole


class AdministrationRepository:
    """Keep catalogue and membership queries outside HTTP routes."""

    def __init__(self, session: AsyncSession) -> None:
        """Use the business service's transaction."""
        self.db = session

    async def promotion(self, promotion_id: int, *, lock: bool = False) -> Promotion | None:
        """Read a promotion, optionally locking its archive state before a mutation."""
        statement = select(Promotion).where(Promotion.id == promotion_id)
        if lock:
            statement = statement.with_for_update()
        return await self.db.scalar(statement)

    async def member_counts(self, ids: list[int]) -> dict[int, int]:
        """Count current memberships in one grouped query for a page of promotions."""
        rows = await self.db.execute(
            select(UserPromotion.promotion_id, func.count())
            .where(UserPromotion.promotion_id.in_(ids))
            .group_by(UserPromotion.promotion_id)
        )
        return dict(rows.all())

    async def student_counts(self, ids: list[int]) -> dict[int, int]:
        """Count students separately from role-independent promotion memberships."""
        rows = await self.db.execute(
            select(UserPromotion.promotion_id, func.count())
            .join(UserRole, UserRole.user_id == UserPromotion.user_id)
            .join(Role)
            .where(UserPromotion.promotion_id.in_(ids), Role.code == "user")
            .group_by(UserPromotion.promotion_id)
        )
        return dict(rows.all())

    @staticmethod
    def users_statement(
        *, role: str | None, status: str | None, promotion_id: int | None
    ) -> Select[tuple[User]]:
        """Build account filters with EXISTS to avoid duplicate rows from multiple roles."""
        statement = select(User).where(User.is_bootstrap.is_(False))
        if status is not None:
            statement = statement.where(User.status == status)
        if role is not None:
            statement = statement.where(
                select(UserRole.user_id)
                .join(Role)
                .where(UserRole.user_id == User.id, Role.code == role)
                .exists()
            )
        if promotion_id is not None:
            statement = statement.where(
                select(UserPromotion.user_id)
                .where(UserPromotion.user_id == User.id, UserPromotion.promotion_id == promotion_id)
                .exists()
            )
        return statement
