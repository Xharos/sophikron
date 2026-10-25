"""Validated event emission inside the business service's existing transaction."""

from collections.abc import Iterable
from datetime import datetime
from string import Formatter
from typing import Literal

from pydantic import Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ActivityEvent, Promotion, Role, UserRole
from app.schemas.administration import PromotionCreate
from app.schemas.auth import InputModel, RoleCodes


class EmptyData(InputModel):
    """Reject arbitrary metadata, particularly credentials and copied personal identities."""


class PromotionChanges(InputModel):
    """Describe changed promotion fields without storing arbitrary request bodies."""

    changed_fields: list[Literal["year", "identifier", "color"]] = Field(max_length=3)
    previous: PromotionCreate
    current: PromotionCreate


class CreatedAccount(InputModel):
    """Preserve the full initial grant combination without any copied account identity."""

    roles: RoleCodes


class InvitationData(InputModel):
    """Retain invitation intent and transport without credentials or personal identities."""

    delivery: Literal["email", "manual"]
    purpose: Literal["activation", "reset"]


class ProfileChanges(InputModel):
    """Journal changed field names without copying any private old or new values."""

    changed_fields: list[
        Literal[
            "first_name",
            "last_name",
            "email",
            "birth_date",
            "city",
            "postal_code",
            "commune_code",
            "previous_school",
            "baccalaureate",
            "orientation_project",
            "phone",
            "reference_adult",
        ]
    ] = Field(min_length=1, max_length=12)


class RoleChanges(InputModel):
    """Record explicit old and new grants without including private account details."""

    previous_roles: RoleCodes
    roles: RoleCodes


class EventDefinition:
    """Describe one trusted event's payload and reference requirements."""

    def __init__(
        self,
        *,
        subject: bool = False,
        resource: str | None = None,
        payload: type[InputModel] = EmptyData,
        version: int = 1,
        label: str = "Événement",
        icon: str = "clock",
        message: str = "{actor} a effectué une action concernant {subject}.",
    ) -> None:
        """Declare validated metadata and required entity references."""
        self.subject = subject
        self.resource = resource
        self.payload = payload
        if version <= 0:
            raise ValueError("Invalid schema version")
        self.version = version
        if any(
            field not in {None, "actor", "subject", "promotion", "roles"} or spec or conversion
            for _, field, spec, conversion in Formatter().parse(message)
        ):
            raise ValueError("Invalid event message")
        self.label, self.icon, self.message = label, icon, message


EVENTS = {
    "auth.login_succeeded": EventDefinition(
        subject=True,
        label="Connexions",
        icon="login",
        message="{subject} s’est connecté à la plateforme.",
    ),
    "user.created": EventDefinition(
        subject=True,
        payload=CreatedAccount,
        label="Créations de comptes",
        icon="plus",
        message="{actor} a créé le compte de {subject}.",
    ),
    "user.archived": EventDefinition(
        subject=True,
        label="Archivages de comptes",
        icon="archive",
        message="{actor} a archivé le compte de {subject} et révoqué ses accès.",
    ),
    "user.reactivated": EventDefinition(
        subject=True,
        label="Réactivations de comptes",
        icon="restore",
        message="{actor} a réactivé le compte de {subject}.",
    ),
    "user.profile_updated": EventDefinition(
        subject=True,
        payload=ProfileChanges,
        label="Modifications de fiches",
        icon="profile",
        message="{actor} a mis à jour la fiche de {subject}.",
    ),
    "user.roles_updated": EventDefinition(
        subject=True,
        payload=RoleChanges,
        label="Changements de rôles",
        icon="admin",
        message="{actor} a changé les rôles de {roles}.",
    ),
    "auth.password_reset": EventDefinition(
        subject=True,
        label="Réinitialisations de mots de passe",
        icon="lock",
        message="{subject} a réinitialisé son mot de passe.",
    ),
    "invitation.issued": EventDefinition(
        subject=True,
        payload=InvitationData,
        label="Invitations",
        icon="email",
        message="{actor} a généré une invitation pour {subject}.",
    ),
    "promotion.created": EventDefinition(
        resource="promotion",
        label="Créations de promotions",
        icon="promotions",
        message="{actor} a créé la promotion {promotion}.",
    ),
    "promotion.updated": EventDefinition(
        resource="promotion",
        payload=PromotionChanges,
        label="Modifications de promotions",
        icon="edit",
        message="{actor} a modifié la promotion {promotion}.",
    ),
    "promotion.archived": EventDefinition(
        resource="promotion",
        label="Archivages de promotions",
        icon="archive",
        message="{actor} a archivé la promotion {promotion}.",
    ),
    "promotion.reactivated": EventDefinition(
        resource="promotion",
        label="Réactivations de promotions",
        icon="restore",
        message="{actor} a réactivé la promotion {promotion}.",
    ),
    "promotion.member_added": EventDefinition(
        subject=True,
        resource="promotion",
        label="Ajouts à une promotion",
        icon="plus",
        message="{actor} a ajouté {subject} à la promotion {promotion}.",
    ),
    "promotion.member_removed": EventDefinition(
        subject=True,
        resource="promotion",
        label="Retraits d’une promotion",
        icon="remove",
        message="{actor} a retiré {subject} de la promotion {promotion}.",
    ),
}


def highest_role(roles: Iterable[str]) -> str | None:
    """Return the highest supported grant, or no role for a system/unknown principal.

    Parameters
    ----------
    roles
        Explicit role codes at the moment of the action.

    Returns
    -------
    str | None
        Administrator, teacher or student code, in descending priority.
    """
    grants = set(roles)
    return next((role for role in ("admin", "teacher", "user") if role in grants), None)


async def capture_roles(session: AsyncSession, ids: set[int]) -> dict[int, str | None]:
    """Batch role snapshots and reuse them only inside the current transaction.

    Parameters
    ----------
    session
        Business transaction owning these audit facts.
    ids
        Distinct participant IDs, including all members of a batch operation.

    Returns
    -------
    dict[int, str | None]
        Highest roles for every requested participant.
    """
    transaction = session.sync_session.get_transaction()
    state = session.info.get("activity_role_snapshots")
    if state is None or state[0] is not transaction:
        state = (transaction, {})
        session.info["activity_role_snapshots"] = state
    cache: dict[int, str | None] = state[1]
    missing = ids - cache.keys()
    if missing:
        grants: dict[int, list[str]] = {identifier: [] for identifier in missing}
        for user_id, code in await session.execute(
            select(UserRole.user_id, Role.code).join(Role).where(UserRole.user_id.in_(missing))
        ):
            grants[user_id].append(code)
        cache.update({user_id: highest_role(roles) for user_id, roles in grants.items()})
    return {identifier: cache[identifier] for identifier in ids}


def forget_role_snapshot(session: AsyncSession, user_id: int) -> None:
    """Invalidate one transaction-local snapshot after a role assignment changes.

    Parameters
    ----------
    session
        Current business session.
    user_id
        Participant whose roles were changed after its previous event.
    """
    state = session.info.get("activity_role_snapshots")
    if state is not None:
        state[1].pop(user_id, None)


async def record_event(
    session: AsyncSession,
    event_type: str,
    actor_user_id: int | None,
    *,
    subject_user_id: int | None = None,
    resource_type: str | None = None,
    resource_id: int | None = None,
    data: dict[str, object] | None = None,
    occurred_at: datetime | None = None,
    promotion: Promotion | None = None,
) -> None:
    """Stage a validated successful event; the caller owns commit and resource validation.

    Parameters
    ----------
    session
        The same transaction/session as the successful business operation.
    event_type
        A code declared in EVENTS with its payload and reference requirements.
    """
    definition = EVENTS[event_type]
    if definition.subject != (subject_user_id is not None):
        raise ValueError("Invalid event subject")
    if resource_type != definition.resource or (resource_type is None) != (resource_id is None):
        raise ValueError("Invalid event resource")
    if any(
        identifier is not None and identifier <= 0
        for identifier in (actor_user_id, subject_user_id, resource_id)
    ):
        raise ValueError("Invalid event identifier")
    payload = definition.payload.model_validate(data or {}).model_dump(mode="json")
    snapshots = await capture_roles(
        session, {item for item in (actor_user_id, subject_user_id) if item is not None}
    )
    promotion_snapshot = None
    if resource_type == "promotion":
        promotion = promotion or await session.get(Promotion, resource_id)
        if promotion is None or promotion.id != resource_id:
            raise ValueError("Invalid promotion reference")
        promotion_snapshot = PromotionCreate.model_validate(
            {field: getattr(promotion, field) for field in ("identifier", "year", "color")}
        ).model_dump()
    event = ActivityEvent(
        event_type=event_type,
        schema_version=definition.version,
        actor_user_id=actor_user_id,
        subject_user_id=subject_user_id,
        actor_role=snapshots.get(actor_user_id),
        subject_role=snapshots.get(subject_user_id),
        promotion_snapshot=promotion_snapshot,
        resource_type=resource_type,
        resource_id=resource_id,
        data=payload,
    )
    if occurred_at is not None:
        event.occurred_at = occurred_at
    session.add(event)
