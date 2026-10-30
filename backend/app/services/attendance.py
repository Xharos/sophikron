"""Authorize roster exports before decrypting names or rendering private PDFs."""

import anyio
from sqlalchemy import select

from app.models import Promotion, PromotionCustomGroup, PromotionCustomGroupMember, UserPromotion
from app.repositories.groups import GroupsRepository
from app.services.activity import record_event
from app.services.attendance_pdf import (
    AttendanceGroup,
    AttendanceStudent,
    AttendanceVariant,
    group_label,
    render_attendance_pdf,
)
from app.services.auth import AuthService, UserContext
from app.services.errors import AuthError


class AttendanceService:
    """Generate a transient document inside the caller's current student-directory scope."""

    def __init__(self, auth: AuthService) -> None:
        """Reuse authenticated request resources and the authoritative pupil repository."""
        self.auth = auth

    async def generate(
        self, actor: UserContext, promotion_id: int, variant: AttendanceVariant = "roster"
    ) -> bytes:
        """Read the complete authorized roster and render it outside the database transaction.

        Parameters
        ----------
        actor
            Authenticated requester; permissions and identity are checked again in the database.
        promotion_id
            Promotion whose current pupils should be exported.

        Returns
        -------
        bytes
            An in-memory PDF with no persistent copy or secret-bearing download link.
        """
        async with self.auth.db.begin():
            user = await self.auth._actor(actor)
            permissions = await self.auth.repo.permissions(actor.id)
            if user.is_bootstrap or not {"users.read", "teaching.read"}.intersection(permissions):
                raise AuthError(403, "Vous n’avez pas accès à cette action.")
            if "users.read" not in permissions:
                membership = await self.auth.db.get(UserPromotion, (actor.id, promotion_id))
                if membership is None:
                    raise AuthError(404, "Promotion introuvable.")
            promotion = await self.auth.db.get(Promotion, promotion_id)
            if promotion is None:
                raise AuthError(404, "Promotion introuvable.")
            cipher = self.auth.cipher
            pupils = await GroupsRepository(self.auth.db).pupils(promotion_id)
            assignments = (
                await GroupsRepository(self.auth.db).assignments(
                    [pupil.id for pupil in pupils], promotion_ids={promotion_id}
                )
                if variant != "roster"
                else {}
            )
            students = [
                AttendanceStudent(
                    last_name=cipher.decrypt(pupil.id, "last_name", pupil.last_name_encrypted),
                    first_name=cipher.decrypt(pupil.id, "first_name", pupil.first_name_encrypted),
                    archived=pupil.status == "disabled",
                    active=pupil.status == "active",
                    assignments=tuple(
                        next(
                            (
                                group_label(kind, item.number)
                                for item in assignments.get(pupil.id, [])
                                if item.kind == kind
                            ),
                            "",
                        )
                        for kind in ("halves", "thirds", "kholles")
                    ),
                )
                for pupil in pupils
            ]
            indexed = dict(zip((pupil.id for pupil in pupils), students, strict=True))
            partitions = (
                await GroupsRepository(self.auth.db).partitions(promotion_id, set(indexed))
                if variant in {"halves", "thirds", "kholles", "global"}
                else []
            )
            defined = [partition["kind"] for partition in partitions if partition["groups"]]
            groups = []
            if variant in {"halves", "thirds", "kholles"}:
                groups = [
                    AttendanceGroup(
                        f"Groupe {group_label(variant, group.number)}",
                        [indexed[identifier] for identifier in group.student_ids],
                    )
                    for partition in partitions
                    if partition["kind"] == variant
                    for group in partition["groups"]
                ]
                assigned = {
                    identifier
                    for partition in partitions
                    if partition["kind"] == variant
                    for group in partition["groups"]
                    for identifier in group.student_ids
                }
                if groups and set(indexed) - assigned:
                    groups.append(
                        AttendanceGroup(
                            "Non affectés",
                            [
                                student
                                for identifier, student in indexed.items()
                                if identifier not in assigned
                            ],
                        )
                    )
            elif variant == "custom":
                custom = await self.auth.db.scalars(
                    select(PromotionCustomGroup)
                    .where(
                        PromotionCustomGroup.promotion_id == promotion_id,
                        PromotionCustomGroup.is_active.is_(True),
                    )
                    .order_by(PromotionCustomGroup.name)
                )
                members = list(
                    await self.auth.db.scalars(
                        select(PromotionCustomGroupMember).where(
                            PromotionCustomGroupMember.promotion_id == promotion_id,
                        )
                    )
                )
                groups = [
                    AttendanceGroup(
                        group.name,
                        [
                            indexed[member.user_id]
                            for member in members
                            if member.group_id == group.id and member.user_id in indexed
                        ],
                    )
                    for group in custom
                ]
            if variant in {"halves", "thirds", "kholles", "custom"} and not groups:
                raise AuthError(404, "Aucun groupe enregistré pour ce document.")
            requested_by = " ".join(
                (
                    cipher.decrypt(user.id, "last_name", user.last_name_encrypted).upper(),
                    cipher.decrypt(user.id, "first_name", user.first_name_encrypted).title(),
                )
            )
            name, color = f"{promotion.identifier} - {promotion.year}", promotion.color
            generated_at = self.auth.clock()
        result = await anyio.to_thread.run_sync(
            render_attendance_pdf,
            name,
            color,
            students,
            requested_by,
            generated_at,
            variant,
            groups,
            defined,
        )
        async with self.auth.db.begin():
            await record_event(
                self.auth.db,
                "promotion.attendance_exported",
                actor.id,
                resource_type="promotion",
                resource_id=promotion_id,
                data={"variant": variant, "student_count": len(students)},
            )
        return result
