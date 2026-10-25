"""Private profile reads and field-authorized, transactional school profile updates."""

import json
from datetime import date

from pydantic import ValidationError
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import aliased

from app.models import Promotion, User, UserPromotion, UserRole
from app.schemas.administration import PromotionBadge
from app.schemas.profile import (
    PRIVATE_PROFILE_FIELDS,
    AdminProfileUpdate,
    FullProfile,
    OrientationUpdate,
    SchoolProfile,
)
from app.services.activity import forget_role_snapshot, record_event
from app.services.auth import AuthService, UserContext
from app.services.communes import validate_commune
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
                roles_changed = (
                    await self.replace_roles(actor, user, roles) if roles is not None else False
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
                if changed or roles_changed:
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
                await self.db.flush()
                return await self.present(actor, user)
        except IntegrityError:
            raise AuthError(409, "Cette adresse email est déjà utilisée.") from None
