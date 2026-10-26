"""SQL reads and replacements for promotion group partitions."""

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    PromotionGroup,
    PromotionGroupMember,
    PromotionPartition,
    Role,
    User,
    UserPromotion,
    UserRole,
)
from app.schemas.groups import GroupAssignment, GroupDraft


class GroupsRepository:
    """Keep partition persistence separate from authorization and balancing rules."""

    def __init__(self, db: AsyncSession) -> None:
        """Use the caller's transaction-bound database session."""
        self.db = db

    async def assignments(
        self,
        user_ids: list[int],
        *,
        promotion_ids: set[int] | None = None,
        staff_id: int | None = None,
    ) -> dict[int, list[GroupAssignment]]:
        """Batch saved assignments, restricted to current pupils and authorized promotions.

        Parameters
        ----------
        user_ids
            Already authorized directory or profile account IDs.
        promotion_ids
            Optional explicit promotion scope; an empty set returns no assignments.
        staff_id
            Require this staff member's current membership in each returned promotion.

        Returns
        -------
        dict[int, list[GroupAssignment]]
            Minimal saved group references grouped by pupil ID.
        """
        if not user_ids or promotion_ids == set():
            return {}
        statement = select(PromotionGroupMember).where(
            PromotionGroupMember.user_id.in_(user_ids),
            select(UserRole.user_id)
            .join(Role)
            .where(UserRole.user_id == PromotionGroupMember.user_id, Role.code == "user")
            .exists(),
        )
        if promotion_ids is not None:
            statement = statement.where(PromotionGroupMember.promotion_id.in_(promotion_ids))
        if staff_id is not None:
            statement = statement.where(
                select(UserPromotion.user_id)
                .where(
                    UserPromotion.user_id == staff_id,
                    UserPromotion.promotion_id == PromotionGroupMember.promotion_id,
                )
                .exists()
            )
        result: dict[int, list[GroupAssignment]] = {}
        for member in await self.db.scalars(
            statement.order_by(PromotionGroupMember.promotion_id, PromotionGroupMember.kind)
        ):
            result.setdefault(member.user_id, []).append(
                GroupAssignment(
                    promotion_id=member.promotion_id,
                    kind=member.kind,
                    number=member.group_number,
                )
            )
        return result

    async def pupils(self, promotion_id: int) -> list[User]:
        """Return all permanent pupils, including pending and archived promotion members."""
        return list(
            await self.db.scalars(
                select(User)
                .join(UserPromotion)
                .where(
                    UserPromotion.promotion_id == promotion_id,
                    User.is_bootstrap.is_(False),
                    select(UserRole.user_id)
                    .join(Role)
                    .where(UserRole.user_id == User.id, Role.code == "user")
                    .exists(),
                )
                .order_by(User.id)
            )
        )

    async def partitions(self, promotion_id: int, pupil_ids: set[int]) -> list[dict]:
        """Read all partitions in three queries, hiding assignments of former pupils."""
        partitions = list(
            await self.db.scalars(
                select(PromotionPartition)
                .where(PromotionPartition.promotion_id == promotion_id)
                .order_by(PromotionPartition.kind)
            )
        )
        groups = list(
            await self.db.scalars(
                select(PromotionGroup)
                .where(PromotionGroup.promotion_id == promotion_id)
                .order_by(PromotionGroup.number)
            )
        )
        members = list(
            await self.db.scalars(
                select(PromotionGroupMember)
                .where(
                    PromotionGroupMember.promotion_id == promotion_id,
                    PromotionGroupMember.user_id.in_(pupil_ids),
                )
                .order_by(PromotionGroupMember.user_id)
            )
        )
        assigned: dict[tuple[str, int], list[int]] = {}
        for member in members:
            assigned.setdefault((member.kind, member.group_number), []).append(member.user_id)
        return [
            dict(
                kind=partition.kind,
                revision=partition.revision,
                target_size=partition.target_size,
                groups=[
                    GroupDraft(
                        number=group.number,
                        x=group.x,
                        y=group.y,
                        student_ids=assigned.get((group.kind, group.number), []),
                    )
                    for group in groups
                    if group.kind == partition.kind
                ],
            )
            for partition in partitions
        ]

    async def replace(self, promotion_id: int, kind: str, groups: list[GroupDraft]) -> None:
        """Replace only this partition's bubbles and assignments; retain other partitions."""
        await self.db.execute(
            delete(PromotionGroup).where(
                PromotionGroup.promotion_id == promotion_id, PromotionGroup.kind == kind
            )
        )
        self.db.add_all(
            [
                PromotionGroup(
                    promotion_id=promotion_id,
                    kind=kind,
                    number=group.number,
                    x=group.x,
                    y=group.y,
                )
                for group in groups
            ]
        )
        await self.db.flush()
        self.db.add_all(
            [
                PromotionGroupMember(
                    promotion_id=promotion_id,
                    kind=kind,
                    user_id=user_id,
                    group_number=group.number,
                )
                for group in groups
                for user_id in group.student_ids
            ]
        )
        await self.db.flush()
