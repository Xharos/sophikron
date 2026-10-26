"""Authorized, atomic group editing and independently randomized partitions."""

import secrets
from math import ceil

from sqlalchemy import select

from app.models import Promotion, PromotionPartition, UserPromotion
from app.repositories.groups import GroupsRepository
from app.schemas.administration import PromotionPage, PromotionResponse
from app.schemas.groups import (
    GroupDraft,
    GroupStudent,
    PartitionGenerate,
    PartitionKind,
    PartitionResponse,
    PartitionSave,
    PartitionVersion,
    PromotionGroupsResponse,
)
from app.services.activity import record_event
from app.services.administration import AdministrationService
from app.services.auth import AuthService, UserContext
from app.services.errors import AuthError


def generate_groups(
    kind: PartitionKind, student_ids: list[int], target_size: int
) -> list[GroupDraft]:
    """Shuffle pupils, balancing halves/thirds and leaving only one khôlle remainder.

    Parameters
    ----------
    kind
        Independent half, third or khôlle partition.
    student_ids
        Current promotion pupil IDs, each occurring once.
    target_size
        Khôlle generation target, between two and five.

    Returns
    -------
    list[GroupDraft]
        Numbered bubbles ready for manual editing before saving.
    """
    if not student_ids:
        raise AuthError(422, "Ajoutez des élèves à cette promotion avant de générer des groupes.")
    count = {"halves": 2, "thirds": 3}.get(kind, ceil(len(student_ids) / target_size))
    shuffled = student_ids.copy()
    secrets.SystemRandom().shuffle(shuffled)
    return [
        GroupDraft(
            number=index + 1,
            x=(index % 3) * 300 + 20,
            y=(index // 3) * 350 + 20,
            student_ids=(
                shuffled[index * target_size : (index + 1) * target_size]
                if kind == "kholles"
                else shuffled[index::count]
            ),
        )
        for index in range(count)
    ]


def validate_groups(
    kind: PartitionKind, groups: list[GroupDraft], pupil_ids: set[int], target_size: int = 3
) -> None:
    """Reject incomplete, duplicate, foreign or incorrectly sized saved assignments.

    Parameters
    ----------
    kind
        Partition whose structural and size rules must hold.
    groups
        Complete proposed replacement, including bubble positions.
    pupil_ids
        Current authoritative set of pupils in the promotion.
    target_size
        Required khôlle size, except for a single group containing the division remainder.
    """
    numbers = sorted(group.number for group in groups)
    expected_count = {"halves": 2, "thirds": 3}.get(kind, len(groups))
    if len(groups) != expected_count or numbers != list(range(1, len(groups) + 1)):
        raise AuthError(422, "Le nombre ou la numérotation des groupes est invalide.")
    assigned = [pupil for group in groups for pupil in group.student_ids]
    if len(assigned) != len(set(assigned)) or set(assigned) != pupil_ids:
        raise AuthError(422, "Chaque élève de la promotion doit apparaître exactement une fois.")
    sizes = [len(group.student_ids) for group in groups]
    if kind == "kholles":
        full_groups, remainder = divmod(len(pupil_ids), target_size)
        expected_sizes = [target_size] * full_groups + ([remainder] if remainder else [])
        if sorted(sizes) != sorted(expected_sizes):
            exception = (
                f", sauf un seul groupe de {remainder} élève(s) pour le reste" if remainder else ""
            )
            raise AuthError(
                422, f"Chaque groupe de khôlle doit contenir {target_size} élèves{exception}."
            )
    elif max(sizes) - min(sizes) > 1:
        raise AuthError(422, "Équilibrez les groupes : l’écart maximal autorisé est d’un élève.")


class GroupsService:
    """Own group transactions and recheck current permissions and promotion scope."""

    def __init__(self, auth: AuthService) -> None:
        """Share authenticated request resources and isolate persistence."""
        self.auth = auth
        self.db = auth.db
        self.repo = GroupsRepository(self.db)

    async def _authorize(self, actor: UserContext, *, write: bool = False) -> bool:
        """Return global read scope or reject callers without a current staff capability."""
        current = await self.auth._actor(actor)
        permissions = await self.auth.repo.permissions(actor.id)
        if current.is_bootstrap:
            raise AuthError(403, "Vous n’avez pas accès à cette action.")
        if write:
            if "promotions.manage" not in permissions:
                raise AuthError(403, "Vous n’avez pas accès à cette action.")
            return True
        if "promotions.read" in permissions:
            return True
        if not {"teaching.read", "kholleur.access"}.intersection(permissions):
            raise AuthError(403, "Vous n’avez pas accès à cette action.")
        return False

    async def _promotion(self, actor: UserContext, promotion_id: int, *, write: bool) -> Promotion:
        """Hide unrelated promotions and prohibit editing archived promotions."""
        global_scope = await self._authorize(actor, write=write)
        if not global_scope and await self.db.get(UserPromotion, (actor.id, promotion_id)) is None:
            raise AuthError(404, "Promotion introuvable.")
        promotion = await self.db.get(Promotion, promotion_id)
        if promotion is None:
            raise AuthError(404, "Promotion introuvable.")
        if write and not promotion.is_active:
            raise AuthError(409, "Cette promotion est archivée ; ses groupes restent consultables.")
        return promotion

    async def promotions(
        self,
        actor: UserContext,
        *,
        offset: int,
        limit: int,
        q: str | None,
        is_active: bool | None,
    ) -> PromotionPage:
        """Expose assigned promotions to khôlleurs without granting student profile access."""
        from sqlalchemy import func

        async with self.db.begin():
            global_scope = await self._authorize(actor)
            statement = select(Promotion)
            if not global_scope:
                statement = statement.join(UserPromotion).where(UserPromotion.user_id == actor.id)
            if is_active is not None:
                statement = statement.where(Promotion.is_active == is_active)
            if q:
                value = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                statement = statement.where(Promotion.identifier.ilike(f"%{value}%", escape="\\"))
            total = await self.db.scalar(select(func.count()).select_from(statement.subquery()))
            items = list(
                await self.db.scalars(
                    statement.order_by(Promotion.year.desc(), Promotion.identifier, Promotion.id)
                    .offset(offset)
                    .limit(limit)
                )
            )
            return PromotionPage(
                items=await AdministrationService(self.auth)._promotion_profiles(items),
                total=total,
                offset=offset,
                limit=limit,
            )

    async def read(self, actor: UserContext, promotion_id: int) -> PromotionGroupsResponse:
        """Return current names and partitions only after verifying promotion access."""
        async with self.db.begin():
            await self._promotion(actor, promotion_id, write=False)
            pupils = await self.repo.pupils(promotion_id)
            return PromotionGroupsResponse(
                students=[
                    GroupStudent(
                        id=pupil.id,
                        first_name=self.auth.cipher.decrypt(
                            pupil.id, "first_name", pupil.first_name_encrypted
                        ),
                        last_name=self.auth.cipher.decrypt(
                            pupil.id, "last_name", pupil.last_name_encrypted
                        ),
                    )
                    for pupil in pupils
                ],
                partitions=await self.repo.partitions(promotion_id, {pupil.id for pupil in pupils}),
            )

    async def promotion(self, actor: UserContext, promotion_id: int) -> PromotionResponse:
        """Read one promotion's display metadata inside current staff scope."""
        async with self.db.begin():
            promotion = await self._promotion(actor, promotion_id, write=False)
            return (await AdministrationService(self.auth)._promotion_profiles([promotion]))[0]

    async def _version(
        self,
        promotion_id: int,
        kind: PartitionKind,
        data: PartitionVersion,
    ) -> PromotionPartition | None:
        """Reject stale writes, including stale deletion or regeneration requests."""
        partition = await self.db.get(PromotionPartition, (promotion_id, kind))
        if (partition.revision if partition else None) != data.expected_revision:
            raise AuthError(
                409, "Cette répartition a changé. Rechargez les groupes avant de continuer."
            )
        return partition

    async def _roster(self, promotion_id: int, roster_ids: list[int]) -> set[int]:
        """Reject a draft when promotion membership or pupil roles changed meanwhile."""
        ids = {pupil.id for pupil in await self.repo.pupils(promotion_id)}
        if len(roster_ids) != len(set(roster_ids)) or set(roster_ids) != ids:
            raise AuthError(409, "La liste des élèves a changé. Rechargez les groupes.")
        return ids

    async def preview(
        self,
        actor: UserContext,
        promotion_id: int,
        kind: PartitionKind,
        data: PartitionGenerate,
    ) -> list[GroupDraft]:
        """Generate a server-randomized draft without replacing the saved partition."""
        async with self.db.begin():
            await self.auth._lifecycle_lock()
            await self._promotion(actor, promotion_id, write=True)
            await self._version(promotion_id, kind, data)
            ids = await self._roster(promotion_id, data.roster_ids)
            return generate_groups(kind, sorted(ids), data.target_size)

    async def save(
        self,
        actor: UserContext,
        promotion_id: int,
        kind: PartitionKind,
        data: PartitionSave,
    ) -> PartitionResponse:
        """Validate and replace one partition atomically, with a version and audit fact."""
        async with self.db.begin():
            await self.auth._lifecycle_lock()
            promotion = await self._promotion(actor, promotion_id, write=True)
            partition = await self._version(promotion_id, kind, data)
            ids = await self._roster(promotion_id, data.roster_ids)
            validate_groups(kind, data.groups, ids, data.target_size)
            groups = [
                group.model_copy(update={"student_ids": sorted(group.student_ids)})
                for group in sorted(data.groups, key=lambda group: group.number)
            ]
            if partition is None:
                partition = PromotionPartition(promotion_id=promotion_id, kind=kind)
                self.db.add(partition)
            partition.revision = secrets.token_hex(16)
            partition.target_size = data.target_size
            await self.db.flush()
            await self.repo.replace(promotion_id, kind, groups)
            await record_event(
                self.db,
                "promotion.groups_saved",
                actor.id,
                resource_type="promotion",
                resource_id=promotion_id,
                promotion=promotion,
                data={"kind": kind, "group_count": len(data.groups), "student_count": len(ids)},
            )
            return PartitionResponse(
                kind=kind,
                revision=partition.revision,
                target_size=partition.target_size,
                groups=groups,
            )

    async def delete(
        self,
        actor: UserContext,
        promotion_id: int,
        kind: PartitionKind,
        data: PartitionVersion,
    ) -> None:
        """Delete only the requested partition; retain pupils and other partitions."""
        async with self.db.begin():
            await self.auth._lifecycle_lock()
            promotion = await self._promotion(actor, promotion_id, write=True)
            partition = await self._version(promotion_id, kind, data)
            if partition is None:
                raise AuthError(404, "Répartition introuvable.")
            await self.db.delete(partition)
            await record_event(
                self.db,
                "promotion.groups_deleted",
                actor.id,
                resource_type="promotion",
                resource_id=promotion_id,
                promotion=promotion,
                data={"kind": kind},
            )
