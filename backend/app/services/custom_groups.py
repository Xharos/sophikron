"""Authorized named audiences with overlapping, promotion-bound pupil membership."""

from uuid import uuid4

from sqlalchemy import delete, select

from app.models import (
    PromotionCustomGroup,
    PromotionCustomGroupMember,
    TimetableCalendar,
    TimetableYear,
)
from app.schemas.groups import CustomGroupSave, CustomGroupVersion
from app.services.activity import record_event
from app.services.auth import UserContext
from app.services.errors import AuthError
from app.services.groups import GroupsService


class CustomGroupsService(GroupsService):
    """Reuse promotion authorization while storing custom groups separately from partitions."""

    async def read_custom(self, actor: UserContext, promotion_id: int) -> dict:
        """Read named groups and their memberships only inside the caller's promotion scope."""
        async with self.db.begin():
            await self._promotion(actor, promotion_id, write=False)
            groups = list(
                await self.db.scalars(
                    select(PromotionCustomGroup)
                    .where(
                        PromotionCustomGroup.promotion_id == promotion_id,
                        PromotionCustomGroup.is_active.is_(True),
                    )
                    .order_by(PromotionCustomGroup.name)
                )
            )
            members = list(
                await self.db.scalars(
                    select(PromotionCustomGroupMember).where(
                        PromotionCustomGroupMember.promotion_id == promotion_id
                    )
                )
            )
            if await self.active_only(actor):
                active_ids = {
                    pupil.id
                    for pupil in await self.repo.pupils(promotion_id)
                    if pupil.status == "active"
                }
                members = [member for member in members if member.user_id in active_ids]
            live = await self.db.scalar(
                select(TimetableCalendar.id).where(
                    TimetableCalendar.promotion_id == promotion_id,
                    TimetableCalendar.is_archived.is_(False),
                    TimetableCalendar.is_paused.is_(False),
                )
            )
            return {
                "live": live is not None,
                "groups": [
                    {
                        "id": group.id,
                        "name": group.name,
                        "revision": group.revision,
                        "x": group.x,
                        "y": group.y,
                        "student_ids": [
                            item.user_id for item in members if item.group_id == group.id
                        ],
                    }
                    for group in groups
                ],
            }

    async def save_custom(
        self, actor: UserContext, promotion_id: int, identifier: int, data: CustomGroupSave
    ) -> dict:
        """Check the roster, revision and live acknowledgement before replacing members."""
        async with self.db.begin():
            await self.auth._lifecycle_lock()
            await self._promotion(actor, promotion_id, write=True)
            row = await self.db.get(PromotionCustomGroup, identifier) if identifier else None
            if identifier and (
                row is None or row.promotion_id != promotion_id or not row.is_active
            ):
                raise AuthError(404, "Groupe introuvable.")
            if (row.revision if row else None) != data.expected_revision:
                raise AuthError(409, "Ce groupe a changé. Rechargez les groupes.")
            pupils = {pupil.id for pupil in await self.repo.pupils(promotion_id)}
            selected = set(data.student_ids)
            if len(selected) != len(data.student_ids) or not selected <= pupils:
                raise AuthError(422, "Sélectionnez des élèves distincts de cette promotion.")
            name = " ".join(data.name.split())
            if not name:
                raise AuthError(422, "Saisissez un nom de groupe.")
            duplicate = await self.db.scalar(
                select(PromotionCustomGroup.id).where(
                    PromotionCustomGroup.promotion_id == promotion_id,
                    PromotionCustomGroup.name_key == name.casefold(),
                    PromotionCustomGroup.id != identifier,
                )
            )
            if duplicate:
                raise AuthError(409, "Un groupe porte déjà ce nom.")
            live = await self.db.scalar(
                select(TimetableCalendar.id).where(
                    TimetableCalendar.promotion_id == promotion_id,
                    TimetableCalendar.is_archived.is_(False),
                    TimetableCalendar.is_paused.is_(False),
                )
            )
            if row is not None and live is not None and not data.confirmed_live:
                raise AuthError(
                    409, "Confirmez la modification des destinataires du calendrier diffusé."
                )
            if row is None:
                row = PromotionCustomGroup(promotion_id=promotion_id, is_active=True)
                self.db.add(row)
            row.name, row.name_key, row.revision = name, name.casefold(), uuid4().hex
            row.x, row.y = data.x, data.y
            await self.db.flush()
            await self.db.execute(
                delete(PromotionCustomGroupMember).where(
                    PromotionCustomGroupMember.group_id == row.id
                )
            )
            self.db.add_all(
                [
                    PromotionCustomGroupMember(
                        group_id=row.id, promotion_id=promotion_id, user_id=identifier
                    )
                    for identifier in sorted(selected)
                ]
            )
            # Membership changes affect personal exports even when session times stay unchanged.
            await record_event(
                self.db,
                "promotion.custom_group_updated"
                if identifier
                else "promotion.custom_group_created",
                actor.id,
                resource_type="promotion",
                resource_id=promotion_id,
                data={"group_name": row.name, "student_count": len(selected)},
            )
            from app.services.timetable import TimetableService

            for year in await self.db.scalars(
                select(TimetableYear)
                .join(TimetableCalendar, TimetableCalendar.id == TimetableYear.calendar_id)
                .where(
                    TimetableCalendar.promotion_id == promotion_id,
                    TimetableCalendar.is_archived.is_(False),
                )
            ):
                await TimetableService(self.auth)._changed(actor, year)
            return {"id": row.id, "revision": row.revision}

    async def delete_custom(
        self, actor: UserContext, promotion_id: int, identifier: int, data: CustomGroupVersion
    ) -> dict:
        """Retire a choice while preserving memberships referenced by existing sessions."""
        async with self.db.begin():
            await self.auth._lifecycle_lock()
            await self._promotion(actor, promotion_id, write=True)
            row = await self.db.get(PromotionCustomGroup, identifier)
            if row is None or row.promotion_id != promotion_id or not row.is_active:
                raise AuthError(404, "Groupe introuvable.")
            if row.revision != data.expected_revision:
                raise AuthError(409, "Ce groupe a changé. Rechargez les groupes.")
            live = await self.db.scalar(
                select(TimetableCalendar.id).where(
                    TimetableCalendar.promotion_id == promotion_id,
                    TimetableCalendar.is_archived.is_(False),
                    TimetableCalendar.is_paused.is_(False),
                )
            )
            if live is not None and not data.confirmed_live:
                raise AuthError(409, "Confirmez la suppression dans cette promotion diffusée.")
            row.is_active = False
            members = await self.db.scalars(
                select(PromotionCustomGroupMember.user_id).where(
                    PromotionCustomGroupMember.group_id == row.id
                )
            )
            await record_event(
                self.db,
                "promotion.custom_group_deleted",
                actor.id,
                resource_type="promotion",
                resource_id=promotion_id,
                data={"group_name": row.name, "student_count": len(list(members))},
            )
            row.name_key = f"retired:{row.id}:{uuid4().hex}"
            row.revision = uuid4().hex
            from app.services.timetable import TimetableService

            for year in await self.db.scalars(
                select(TimetableYear)
                .join(TimetableCalendar, TimetableCalendar.id == TimetableYear.calendar_id)
                .where(
                    TimetableCalendar.promotion_id == promotion_id,
                    TimetableCalendar.is_archived.is_(False),
                )
            ):
                await TimetableService(self.auth)._changed(actor, year)
            return {"id": row.id, "revision": row.revision}
