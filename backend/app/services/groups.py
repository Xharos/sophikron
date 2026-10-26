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
    kind: PartitionKind,
    student_ids: list[int],
    target_size: int,
    archived_ids: set[int] | None = None,
    existing_groups: list[GroupDraft] | None = None,
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
    archived_ids
        Pupils excluded from randomization and all effective-size calculations.
    existing_groups
        Preserve archived pupils' current group numbers and bubble positions.

    Returns
    -------
    list[GroupDraft]
        Numbered bubbles ready for manual editing before saving.
    """
    if not student_ids:
        raise AuthError(422, "Ajoutez des élèves à cette promotion avant de générer des groupes.")
    archived_ids = archived_ids or set()
    shuffled = [student_id for student_id in student_ids if student_id not in archived_ids]
    count = {"halves": 2, "thirds": 3}.get(kind, max(1, ceil(len(shuffled) / target_size)))
    secrets.SystemRandom().shuffle(shuffled)
    groups = [
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
    indexed = {group.number: group for group in groups}
    preserved = set()
    for previous in existing_groups or []:
        archived_members = [pupil for pupil in previous.student_ids if pupil in archived_ids]
        if not archived_members:
            continue
        if previous.number not in indexed:
            indexed[previous.number] = GroupDraft(
                number=previous.number,
                x=previous.x,
                y=previous.y,
                student_ids=[],
            )
        indexed[previous.number].x = previous.x
        indexed[previous.number].y = previous.y
        indexed[previous.number].student_ids.extend(archived_members)
        preserved.update(archived_members)
    for index, pupil in enumerate(sorted(archived_ids - preserved)):
        groups[index % len(groups)].student_ids.append(pupil)
    return [group for _, group in sorted(indexed.items()) if kind != "kholles" or group.student_ids]


def validate_groups(
    kind: PartitionKind,
    groups: list[GroupDraft],
    pupil_ids: set[int],
    target_size: int = 3,
    archived_ids: set[int] | None = None,
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
    archived_ids
        Preserve these assignments while excluding their pupils from size constraints.
    """
    numbers = sorted(group.number for group in groups)
    archived_ids = archived_ids or set()
    expected_count = {"halves": 2, "thirds": 3}.get(kind)
    if (
        len(numbers) != len(set(numbers))
        or expected_count is not None
        and numbers != list(range(1, expected_count + 1))
    ):
        raise AuthError(422, "Le nombre ou la numérotation des groupes est invalide.")
    assigned = [pupil for group in groups for pupil in group.student_ids]
    if len(assigned) != len(set(assigned)) or set(assigned) != pupil_ids:
        raise AuthError(422, "Chaque élève de la promotion doit apparaître exactement une fois.")
    sizes = [sum(pupil not in archived_ids for pupil in group.student_ids) for group in groups]
    if kind == "kholles":
        if any(not group.student_ids for group in groups):
            raise AuthError(422, "Retirez les groupes de khôlle entièrement vides.")
        sizes = [size for size in sizes if size > 0]
        full_groups, remainder = divmod(len(pupil_ids - archived_ids), target_size)
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
                        status=pupil.status,
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

    async def _roster(
        self,
        promotion_id: int,
        roster_ids: list[int],
        archived_ids: list[int],
    ) -> tuple[set[int], set[int]]:
        """Reject a draft when promotion membership or pupil roles changed meanwhile."""
        pupils = await self.repo.pupils(promotion_id)
        ids = {pupil.id for pupil in pupils}
        archived = {pupil.id for pupil in pupils if pupil.status == "disabled"}
        if len(roster_ids) != len(set(roster_ids)) or set(roster_ids) != ids:
            raise AuthError(409, "La liste des élèves a changé. Rechargez les groupes.")
        if len(archived_ids) != len(set(archived_ids)) or set(archived_ids) != archived:
            raise AuthError(409, "Le statut des élèves a changé. Rechargez les groupes.")
        return ids, archived

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
            ids, archived = await self._roster(promotion_id, data.roster_ids, data.archived_ids)
            partitions = await self.repo.partitions(promotion_id, ids)
            existing = next((item["groups"] for item in partitions if item["kind"] == kind), [])
            return generate_groups(kind, sorted(ids), data.target_size, archived, existing)

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
            ids, archived = await self._roster(promotion_id, data.roster_ids, data.archived_ids)
            validate_groups(kind, data.groups, ids, data.target_size, archived)
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
