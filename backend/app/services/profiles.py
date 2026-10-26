"""Private profile reads and field-authorized, transactional school profile updates."""

import json
from datetime import date

from pydantic import ValidationError
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import aliased

from app.core.roles import can_join_promotion
from app.models import Promotion, User, UserPromotion, UserRole
from app.models.lessons import Lesson, LessonCollaborator
from app.models.site import Subject, TeacherSubject
from app.schemas.administration import PromotionBadge
from app.schemas.profile import (
    PRIVATE_PROFILE_FIELDS,
    AdminProfileUpdate,
    FullProfile,
    OrientationUpdate,
    SchoolProfile,
)
from app.services.activity import forget_role_snapshot, record_event, record_subject_changes
from app.services.auth import AuthService, UserContext
from app.services.communes import validate_commune
from app.services.course_rights import (
    course_impact,
    require_impact_acknowledgement,
)
from app.services.errors import AuthError
from app.services.teaching import TeachingService


def calculate_age(birth_date: date | None, today: date) -> int | None:
    """Return completed calendar years, with a February 29 birthday reached on March 1."""
    if birth_date is None:
        return None
    return (
        today.year
        - birth_date.year
        - ((today.month, today.day) < (birth_date.month, birth_date.day))
    )


class ProfileService:
    """Keep encrypted profile details out of directory lists and session bootstrap payloads."""

    def __init__(self, auth: AuthService) -> None:
        """Reuse the request's authentication service, transaction and cipher."""
        self.auth = auth
        self.db = auth.db

    def decode(self, user: User) -> SchoolProfile:
        """Authenticate and decode all private fields only after access has been checked."""
        fields = {}
        for field in PRIVATE_PROFILE_FIELDS:
            value = getattr(user, field + "_encrypted")
            fields[field] = (
                json.loads(self.auth.cipher.decrypt(user.id, field, value))
                if value is not None
                else None
            )
        return SchoolProfile.model_validate(fields)

    async def target(self, actor: UserContext, user_id: int, *, owner: bool = False) -> User:
        """Select an authorized target and hide students outside the current teacher scope."""
        await self.auth._actor(actor, permission=None if owner else "profiles.read")
        if owner or "profiles.manage" in await self.auth.repo.permissions(actor.id):
            user = await self.auth.repo.user(actor.id if owner else user_id)
        else:
            user = await self.db.scalar(
                TeachingService(self.auth)
                .students_statement(actor.id, None)
                .where(User.id == user_id)
            )
        if user is None or user.is_bootstrap:
            raise AuthError(404, "Compte introuvable.")
        return user

    async def present(self, actor: UserContext, user: User, *, owner: bool = False) -> FullProfile:
        """Build a private detail DTO with shared promotions and explicit editing capabilities."""
        permissions = await self.auth.repo.permissions(actor.id)
        can_edit_all = not owner and "profiles.manage" in permissions
        statement = select(Promotion).join(UserPromotion).where(UserPromotion.user_id == user.id)
        if not owner and not can_edit_all:
            teacher = aliased(UserPromotion)
            statement = statement.join(teacher, teacher.promotion_id == Promotion.id).where(
                teacher.user_id == actor.id
            )
        promotions = (await self.db.scalars(statement.order_by(Promotion.year.desc()))).all()
        profile = self.decode(user)
        today = self.auth.clock().date()
        age = calculate_age(profile.birth_date, today)
        cipher = self.auth.cipher
        return FullProfile(
            id=user.id,
            username=cipher.decrypt(user.id, "username", user.username_encrypted),
            first_name=cipher.decrypt(user.id, "first_name", user.first_name_encrypted),
            last_name=cipher.decrypt(user.id, "last_name", user.last_name_encrypted),
            email=cipher.decrypt(user.id, "email", user.email_encrypted),
            roles=list(await self.auth.repo.roles(user.id)),
            status=user.status,
            profile_version=user.profile_version,
            profile=profile,
            age=age,
            promotions=[
                PromotionBadge.model_validate(promotion, from_attributes=True)
                for promotion in promotions
            ],
            can_edit_all=can_edit_all,
            subject_ids=list(
                await self.db.scalars(
                    select(TeacherSubject.subject_id).where(TeacherSubject.user_id == user.id)
                )
            )
            if owner or can_edit_all
            else [],
            can_edit_orientation=not owner
            and (can_edit_all or "orientation.manage" in permissions),
        )

    async def read(self, actor: UserContext, user_id: int, *, owner: bool = False) -> FullProfile:
        """Return one authorized detail without extending general account-list contracts."""
        async with self.db.begin():
            user = await self.target(actor, user_id, owner=owner)
            return await self.present(actor, user, owner=owner)

    async def replace_roles(self, actor: UserContext, user: User, roles: list[str]) -> bool:
        """Replace validated grants inside the caller's locked profile transaction.

        Parameters
        ----------
        actor
            Administrator reauthorized by the enclosing transaction.
        user
            Permanent target account locked by the enclosing transaction.
        roles
            Validated explicit role combination.

        Returns
        -------
        bool
            Whether grants changed and a journal event was staged.
        """
        await self.auth._actor(actor, admin=True)
        previous = await self.auth.repo.roles(user.id)
        if set(previous) == set(roles):
            return False
        if user.id == actor.id and "admin" in previous and "admin" not in roles:
            raise AuthError(409, "Vous ne pouvez pas retirer votre propre rôle Administrateur.")
        records = await self.auth.repo.role_records(roles)
        if len(records) != len(roles):
            raise AuthError(422, "Rôle introuvable.")
        await record_event(
            self.db,
            "user.roles_updated",
            actor.id,
            subject_user_id=user.id,
            data={"previous_roles": list(previous), "roles": sorted(roles)},
        )
        if not can_join_promotion(roles):
            promotions = list(
                await self.db.scalars(
                    select(Promotion)
                    .join(UserPromotion)
                    .where(UserPromotion.user_id == user.id)
                    .order_by(Promotion.id)
                )
            )
            await self.db.execute(delete(UserPromotion).where(UserPromotion.user_id == user.id))
            for promotion in promotions:
                await record_event(
                    self.db,
                    "promotion.member_removed",
                    actor.id,
                    subject_user_id=user.id,
                    resource_type="promotion",
                    resource_id=promotion.id,
                    data={"reason": "role_removed"},
                    promotion=promotion,
                )
        await self.db.execute(delete(UserRole).where(UserRole.user_id == user.id))
        self.db.add_all([UserRole(user_id=user.id, role_id=role.id) for role in records])
        forget_role_snapshot(self.db, user.id)
        return True

    async def update(
        self, actor: UserContext, user_id: int, data: AdminProfileUpdate | OrientationUpdate
    ) -> FullProfile:
        """Save allowed fields atomically and reject concurrent profile changes."""
        values = data.model_dump(mode="json", exclude_unset=True)
        version = values.pop("expected_version")
        roles = values.pop("roles", None)
        subject_ids = values.pop("subject_ids", None)
        acknowledged = values.pop("acknowledge_course_impact", False)
        location_fields = {"city", "postal_code", "commune_code"}
        if location_fields.intersection(values):
            if not location_fields.issubset(values):
                raise AuthError(422, "La commune et le code postal doivent être modifiés ensemble.")
            if any(values[field] is not None for field in location_fields):
                if not all(values[field] for field in location_fields):
                    raise AuthError(422, "Sélectionnez une commune et son code postal.")
                values["city"] = await validate_commune(
                    values["commune_code"], values["postal_code"]
                )
        try:
            async with self.db.begin():
                await self.auth._lifecycle_lock()
                user = await self.target(actor, user_id)
                permissions = await self.auth.repo.permissions(actor.id)
                if isinstance(data, AdminProfileUpdate):
                    if "profiles.manage" not in permissions:
                        raise AuthError(403, "Modification réservée aux administrateurs.")
                elif "orientation.manage" not in permissions:
                    raise AuthError(403, "Modification du projet d’orientation interdite.")
                user = await self.auth.repo.user(user.id, lock=True)
                if user.profile_version != version:
                    raise AuthError(
                        409, "Cette fiche a été modifiée. Rechargez-la avant d’enregistrer."
                    )
                previous_roles = set(await self.auth.repo.roles(user.id))
                next_roles = set(roles) if roles is not None else previous_roles
                old_subjects = set(
                    await self.db.scalars(
                        select(TeacherSubject.subject_id).where(TeacherSubject.user_id == user.id)
                    )
                )
                next_subjects = set(subject_ids) if subject_ids is not None else old_subjects
                if not next_roles.intersection({"teacher", "kholleur"}):
                    if subject_ids:
                        raise AuthError(
                            422, "Seul un enseignant ou un khôlleur peut recevoir des matières."
                        )
                    next_subjects = set()
                if subject_ids and user.status == "disabled":
                    raise AuthError(409, "Réactivez le compte avant de lui affecter des matières.")
                if next_subjects:
                    valid = set(
                        await self.db.scalars(
                            select(Subject.id).where(
                                Subject.id.in_(next_subjects), Subject.is_active
                            )
                        )
                    )
                    if valid != next_subjects:
                        raise AuthError(422, "Une matière est inconnue ou archivée.")
                removed = old_subjects - next_subjects
                if previous_roles != next_roles or removed:
                    courses = await course_impact(self.db, user.id)
                    impacted = []
                    revoked_links = []
                    for course in courses:
                        had_teaching = (
                            "teacher" in previous_roles and course.subject_id in old_subjects
                        )
                        has_teaching = (
                            "teacher" in next_roles and course.subject_id in next_subjects
                        )
                        lost_reading = (
                            "kholleur" in previous_roles
                            and "kholleur" not in next_roles
                            and not has_teaching
                            and "admin" not in next_roles
                        )
                        if (had_teaching and not has_teaching) or lost_reading:
                            impacted.append(course)
                        if not has_teaching and "kholleur" not in next_roles:
                            revoked_links.append(course.id)
                    require_impact_acknowledgement(impacted, acknowledged)
                    if impacted:
                        await self.db.execute(
                            update(Lesson)
                            .where(Lesson.id.in_([item.id for item in impacted]))
                            .values(version=Lesson.version + 1)
                        )
                    if revoked_links:
                        await self.db.execute(
                            delete(LessonCollaborator).where(
                                LessonCollaborator.user_id == user.id,
                                LessonCollaborator.lesson_id.in_(revoked_links),
                            )
                        )
                roles_changed = (
                    await self.replace_roles(actor, user, roles) if roles is not None else False
                )
                subjects_changed = old_subjects != next_subjects
                if subjects_changed:
                    await self.db.execute(
                        delete(TeacherSubject).where(TeacherSubject.user_id == user.id)
                    )
                    self.db.add_all(
                        [
                            TeacherSubject(user_id=user.id, subject_id=identifier)
                            for identifier in next_subjects
                        ]
                    )
                existing = self.decode(user).model_dump(mode="json")
                candidate = {
                    **existing,
                    **{
                        key: value for key, value in values.items() if key in PRIVATE_PROFILE_FIELDS
                    },
                }
                try:
                    SchoolProfile.model_validate(candidate)
                except ValidationError:
                    raise AuthError(422, "Les informations de la fiche sont invalides.") from None
                changed = []
                for field, value in values.items():
                    if field in {"first_name", "last_name", "email"}:
                        old = self.auth.cipher.decrypt(
                            user.id, field, getattr(user, field + "_encrypted")
                        )
                    else:
                        old = existing[field]
                    if old == value:
                        continue
                    encoded = (
                        value
                        if field in {"first_name", "last_name", "email"}
                        else json.dumps(value, ensure_ascii=False)
                    )
                    setattr(
                        user,
                        field + "_encrypted",
                        self.auth.cipher.encrypt(user.id, field, encoded)
                        if value is not None
                        else None,
                    )
                    changed.append(field)
                    if field == "email":
                        user.email_lookup = self.auth.cipher.lookup("email", value)
                        user.email_verified_at = None
                        await self.auth.repo.revoke_invitations(user.id, self.auth.clock())
                if changed or roles_changed or subjects_changed:
                    user.profile_version += 1
                    user.updated_at = self.auth.clock()
                if changed:
                    await record_event(
                        self.db,
                        "user.profile_updated",
                        actor.id,
                        subject_user_id=user.id,
                        data={"changed_fields": changed},
                    )
                if subjects_changed:
                    await record_subject_changes(
                        self.db,
                        actor.id,
                        user.id,
                        added=next_subjects - old_subjects,
                        removed=old_subjects - next_subjects,
                        reason="role_removed"
                        if previous_roles.intersection({"teacher", "kholleur"})
                        and not next_roles.intersection({"teacher", "kholleur"})
                        else "manual",
                    )
                await self.db.flush()
                return await self.present(actor, user)
        except IntegrityError:
            raise AuthError(409, "Cette adresse email est déjà utilisée.") from None
