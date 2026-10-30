"""Parameterized dashboard queries without transaction or authorization ownership."""

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.roles import TEACHING_ROLES
from app.models import Promotion, PromotionAccountBlock, Role, User, UserPromotion, UserRole


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

    async def member_counts(self, ids: list[int], *, active_only: bool = False) -> dict[int, int]:
        """Count current memberships in one grouped query for a page of promotions."""
        rows = await self.db.execute(
            select(UserPromotion.promotion_id, func.count())
            .join(User, User.id == UserPromotion.user_id)
            .where(UserPromotion.promotion_id.in_(ids))
            .where(User.status == "active" if active_only else True)
            .group_by(UserPromotion.promotion_id)
        )
        return dict(rows.all())

    async def display_counts(
        self, ids: list[int], *, active_only: bool = False
    ) -> dict[int, dict[str, int]]:
        """Count non-archived pupils, unique teaching accounts and all archived members.

        Parameters
        ----------
        ids
            Authorized promotion page IDs.

        Returns
        -------
        dict[int, dict[str, int]]
            Disjoint display categories; teacher/khôlleur combinations count once.
        """
        pupil = (
            select(UserRole.user_id)
            .join(Role)
            .where(UserRole.user_id == User.id, Role.code == "user")
            .exists()
        )
        teaching = (
            select(UserRole.user_id)
            .join(Role)
            .where(UserRole.user_id == User.id, Role.code.in_(TEACHING_ROLES))
            .exists()
        )
        rows = await self.db.execute(
            select(
                UserPromotion.promotion_id,
                func.count().filter(pupil, User.status != "disabled"),
                func.count().filter(teaching, User.status != "disabled"),
                func.count().filter(User.status == "disabled"),
            )
            .join(User, User.id == UserPromotion.user_id)
            .where(UserPromotion.promotion_id.in_(ids))
            .where(User.status == "active" if active_only else True)
            .group_by(UserPromotion.promotion_id)
        )
        return {
            promotion_id: {
                "non_archived_student_count": students,
                "teaching_count": staff,
                "archived_count": archived,
            }
            for promotion_id, students, staff, archived in rows
        }

    async def promotion_students(self, promotion_id: int) -> list[User]:
        """Select only permanent pupils currently linked to this promotion."""
        return list(
            await self.db.scalars(
                self.users_statement(role="user", status=None, promotion_id=promotion_id).order_by(
                    User.id
                )
            )
        )

    async def blocked_accounts(self, promotion_id: int) -> list[User]:
        """Find recorded blocks independently of later role or membership changes."""
        return list(
            await self.db.scalars(
                select(User)
                .join(PromotionAccountBlock)
                .where(PromotionAccountBlock.promotion_id == promotion_id)
                .order_by(User.id)
            )
        )

    async def account_blocks(self, ids: list[int]) -> dict[int, set[int]]:
        """Load all independent promotion causes for the affected accounts."""
        blocks: dict[int, set[int]] = {}
        for user_id, promotion_id in await self.db.execute(
            select(PromotionAccountBlock.user_id, PromotionAccountBlock.promotion_id).where(
                PromotionAccountBlock.user_id.in_(ids)
            )
        ):
            blocks.setdefault(user_id, set()).add(promotion_id)
        return blocks

    async def student_counts(self, ids: list[int], *, active_only: bool = False) -> dict[int, int]:
        """Count students separately from role-independent promotion memberships."""
        rows = await self.db.execute(
            select(UserPromotion.promotion_id, func.count())
            .join(UserRole, UserRole.user_id == UserPromotion.user_id)
            .join(Role)
            .where(UserPromotion.promotion_id.in_(ids), Role.code == "user")
            .where(
                select(User.id)
                .where(User.id == UserPromotion.user_id, User.status == "active")
                .exists()
                if active_only
                else True
            )
            .group_by(UserPromotion.promotion_id)
        )
        return dict(rows.all())

    @staticmethod
    def users_statement(
        *,
        role: str | None,
        status: str | None,
        promotion_id: int | None,
        exclude_promotion_id: int | None = None,
    ) -> Select[tuple[User]]:
        """Build account filters with EXISTS to avoid duplicate rows from multiple roles."""
        statement = select(User).where(User.is_bootstrap.is_(False))
        if status is not None:
            statement = statement.where(User.status == status)
        if role is not None:
            statement = statement.where(
                select(UserRole.user_id)
                .join(Role)
                .where(
                    UserRole.user_id == User.id,
                    Role.code.in_(TEACHING_ROLES) if role == "teaching" else Role.code == role,
                )
                .exists()
            )
        if promotion_id is not None:
            statement = statement.where(
                select(UserPromotion.user_id)
                .where(UserPromotion.user_id == User.id, UserPromotion.promotion_id == promotion_id)
                .exists()
            )
        if exclude_promotion_id is not None:
            statement = statement.where(
                ~select(UserPromotion.user_id)
                .where(
                    UserPromotion.user_id == User.id,
                    UserPromotion.promotion_id == exclude_promotion_id,
                )
                .exists()
            )
        return statement
