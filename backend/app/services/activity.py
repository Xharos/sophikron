"""Validated event emission inside the business service's existing transaction."""

import json
from collections.abc import Iterable
from datetime import date, datetime
from string import Formatter
from typing import Literal

from pydantic import Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ActivityEvent, Promotion, Role, UserRole
from app.models.site import Subject
from app.schemas.administration import PromotionCreate
from app.schemas.auth import InputModel, RoleCodes
from app.schemas.site import SubjectFields


class EmptyData(InputModel):
    """Reject arbitrary metadata, particularly credentials and copied personal identities."""


class PromotionChanges(InputModel):
    """Describe changed promotion fields without storing arbitrary request bodies."""

    changed_fields: list[Literal["year", "identifier", "color"]] = Field(max_length=3)
    previous: PromotionCreate
    current: PromotionCreate


class AccountArchiveCause(InputModel):
    """Identify an automatic promotion action without copying pupil identities."""

    promotion_id: int | None = Field(default=None, gt=0)
    promotion: PromotionCreate | None = None


class PromotionArchiveCounts(InputModel):
    """Record how many independent blocks and actual login changes were applied."""

    student_blocks: int = Field(default=0, ge=0)
    accounts_changed: int = Field(default=0, ge=0)


class MembershipRemoval(InputModel):
    """Distinguish an automatic eligibility loss from a manual membership removal."""

    reason: Literal["manual", "role_removed"] = "manual"


class GroupActivity(InputModel):
    """Record partition type and aggregate counts without student identities."""

    kind: Literal["halves", "thirds", "kholles"]
    group_count: int | None = Field(default=None, ge=1, le=1000)
    student_count: int | None = Field(default=None, ge=0, le=2000)


class DownloadFacts(InputModel):
    """Keep numeric historical file facts without filenames, bodies or storage paths."""

    file_id: int = Field(gt=0)
    size_bytes: int = Field(gt=0)


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


class SubjectSnapshot(SubjectFields):
    """Preserve public subject identity independently of later renaming or archival."""

    id: int = Field(gt=0)


class SubjectChanges(InputModel):
    """Record only the actual assignment delta and its trusted business cause."""

    added: list[SubjectSnapshot] = Field(default_factory=list, max_length=100)
    removed: list[SubjectSnapshot] = Field(default_factory=list, max_length=100)
    reason: Literal["manual", "role_removed", "account_archived", "subject_archived"] = "manual"


class SubjectActivity(InputModel):
    """Describe a public catalogue operation without copying any teacher identities."""

    action: Literal["created", "updated", "archived"]
    subject: SubjectSnapshot
    previous: SubjectSnapshot | None = None
    changed_fields: list[Literal["name", "icon", "color"]] = Field(
        default_factory=list, max_length=3
    )
    removed_assignments: int = Field(default=0, ge=0)


class SettingsActivity(InputModel):
    """Name modified settings without copying the homepage text into the journal."""

    changed_fields: list[Literal["name", "home_text", "text_color", "holiday_color"]] = Field(
        max_length=4
    )
    previous_name: str = Field(max_length=100)
    name: str = Field(max_length=100)


class CalendarActivity(InputModel):
    """Identify a dated public entry even after deletion, without ambiguous table IDs."""

    entry_type: Literal["timeline", "event"]
    action: Literal["created", "updated", "deleted"]
    name: str = Field(max_length=100)
    starts_on: date
    ends_on: date
    kind: Literal["holiday", "oral", "written", "school", "other"] | None = None
    changed_fields: list[
        Literal["name", "starts_on", "ends_on", "color", "kind", "timeline_ids"]
    ] = Field(default_factory=list, max_length=6)
    timeline_count: int | None = Field(default=None, ge=0, le=20)
    deleted_events: int = Field(default=0, ge=0, le=200)
    retained_events: int = Field(default=0, ge=0, le=200)


class LessonPeriod(InputModel):
    """Keep date rules without copying protected teaching content into the journal."""

    mode: Literal["inherit", "from", "range"]
    starts_on: date | None
    ends_on: date | None


class LessonActivity(InputModel):
    """Bound course audit details to public labels, references and scheduling facts."""

    lesson_title: str = Field(max_length=160)
    element_id: int | None = Field(default=None, gt=0)
    element_kind: Literal["section", "subsection", "text", "youtube", "table", "file"] | None = None
    element_title: str | None = Field(default=None, max_length=200)
    changed_fields: list[
        Literal[
            "title",
            "description",
            "icon",
            "color",
            "body",
            "schedule_mode",
            "starts_on",
            "ends_on",
            "subject_id",
            "responsible_id",
            "audience",
            "table_structure",
        ]
    ] = Field(default_factory=list, max_length=10)
    previous_responsible_id: int | None = None
    previous_subject_id: int | None = None
    removed_count: int | None = Field(default=None, ge=1, le=500)
    direction: Literal["up", "down"] | None = None
    promotion_id: int | None = Field(default=None, gt=0)
    promotion: PromotionCreate | None = None
    previous_period: LessonPeriod | None = None
    period: LessonPeriod | None = None


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
            field not in {None, "actor", "subject", "promotion", "roles", "lesson"}
            or spec
            or conversion
            for _, field, spec, conversion in Formatter().parse(message)
        ):
            raise ValueError("Invalid event message")
        self.label, self.icon, self.message = label, icon, message


EVENTS = {
    "lesson.file_downloaded": EventDefinition(
        subject=True,
        resource="lesson",
        payload=DownloadFacts,
        label="Téléchargements de documents",
        icon="download",
        message="{subject} a téléchargé un document de {lesson}.",
    ),
    "subject.saved": EventDefinition(
        payload=SubjectActivity,
        version=2,
        resource="subject",
        label="Matières enregistrées",
        icon="book",
        message="{actor} a enregistré une matière.",
    ),
    "subject.archived": EventDefinition(
        payload=SubjectActivity,
        version=2,
        resource="subject",
        label="Matières archivées",
        icon="archive",
        message="{actor} a archivé une matière et retiré ses affectations.",
    ),
    "user.subjects_updated": EventDefinition(
        payload=SubjectChanges,
        version=2,
        subject=True,
        label="Affectations des matières",
        icon="book",
        message="{actor} a modifié les matières de {subject}.",
    ),
    "site.updated": EventDefinition(
        payload=SettingsActivity,
        version=2,
        resource="site",
        label="Configuration du site",
        icon="school",
        message="{actor} a modifié la configuration du site.",
    ),
    "calendar.saved": EventDefinition(
        payload=CalendarActivity,
        version=2,
        resource="calendar",
        label="Calendrier enregistré",
        icon="clock",
        message="{actor} a enregistré un élément du calendrier.",
    ),
    "calendar.deleted": EventDefinition(
        payload=CalendarActivity,
        version=2,
        resource="calendar",
        label="Calendrier supprimé",
        icon="remove",
        message="{actor} a supprimé un élément du calendrier.",
    ),
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
        payload=AccountArchiveCause,
        version=2,
        label="Archivages de comptes",
        icon="archive",
        message="{actor} a archivé le compte de {subject} et révoqué ses accès.",
    ),
    "user.reactivated": EventDefinition(
        subject=True,
        payload=AccountArchiveCause,
        version=2,
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
    "promotion.groups_saved": EventDefinition(
        resource="promotion",
        payload=GroupActivity,
        label="Répartitions enregistrées",
        icon="promotions",
        message="{actor} a enregistré une répartition des groupes de {promotion}.",
    ),
    "promotion.groups_deleted": EventDefinition(
        resource="promotion",
        payload=GroupActivity,
        label="Répartitions supprimées",
        icon="remove",
        message="{actor} a supprimé une répartition des groupes de {promotion}.",
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
        payload=PromotionArchiveCounts,
        version=2,
        label="Archivages de promotions",
        icon="archive",
        message="{actor} a archivé la promotion {promotion}.",
    ),
    "promotion.reactivated": EventDefinition(
        resource="promotion",
        payload=PromotionArchiveCounts,
        version=2,
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
        payload=MembershipRemoval,
        version=2,
        label="Retraits d’une promotion",
        icon="remove",
        message="{actor} a retiré {subject} de la promotion {promotion}.",
    ),
}

for _code, _label, _icon, _message in (
    (
        "responsibility_updated",
        "Responsables réaffectés",
        "teacher",
        "{actor} a nommé {subject} responsable de {lesson}.",
    ),
    ("created", "Créations de cours", "book", "{actor} a créé le cours {lesson}."),
    ("updated", "Modifications de cours", "edit", "{actor} a modifié le cours {lesson}."),
    ("deleted", "Suppressions de cours", "remove", "{actor} a supprimé le cours {lesson}."),
    ("element_created", "Ajouts de contenus", "plus", "{actor} a ajouté un élément dans {lesson}."),
    (
        "element_updated",
        "Modifications de contenus",
        "edit",
        "{actor} a modifié un élément dans {lesson}.",
    ),
    (
        "element_deleted",
        "Suppressions de contenus",
        "remove",
        "{actor} a supprimé un élément dans {lesson}.",
    ),
    (
        "element_moved",
        "Déplacements de contenus",
        "arrow",
        "{actor} a déplacé un élément dans {lesson}.",
    ),
    (
        "collaborator_added",
        "Collaborateurs ajoutés",
        "teacher",
        "{actor} a ajouté {subject} comme collaborateur de {lesson}.",
    ),
    (
        "collaborator_removed",
        "Collaborateurs retirés",
        "remove",
        "{actor} a retiré {subject} des collaborateurs de {lesson}.",
    ),
    (
        "promotion_added",
        "Accès aux cours accordés",
        "promotions",
        "{actor} a autorisé une promotion à consulter {lesson}.",
    ),
    (
        "promotion_updated",
        "Périodes d’accès aux cours",
        "clock",
        "{actor} a modifié une période d’accès à {lesson}.",
    ),
    (
        "promotion_removed",
        "Accès aux cours révoqués",
        "lock",
        "{actor} a révoqué l’accès d’une promotion à {lesson}.",
    ),
):
    EVENTS[f"lesson.{_code}"] = EventDefinition(
        subject=_code.startswith("collaborator_") or _code == "responsibility_updated",
        resource="lesson",
        payload=LessonActivity,
        label=_label,
        icon=_icon,
        message=_message,
    )


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
    return next((role for role in ("admin", "teacher", "kholleur", "user") if role in grants), None)


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


async def record_subject_changes(
    session: AsyncSession,
    actor_user_id: int,
    user_id: int,
    *,
    added: set[int],
    removed: set[int],
    reason: Literal["manual", "role_removed", "account_archived", "subject_archived"] = "manual",
) -> None:
    """Stage assignment deltas in bounded audit rows within the caller's transaction.

    Parameters
    ----------
    session
        Locked business transaction, shared with the assignment mutation.
    actor_user_id
        Authorized administrator responsible for the change.
    user_id
        Account whose subject eligibility changed.
    added, removed
        Disjoint subject identifiers, resolved before any catalogue row can disappear.
    reason
        Trusted cause, including automatic revocations.

    Returns
    -------
    None
        Large changes are split to respect the journal's 4096-byte PostgreSQL constraint.
    """
    rows = await session.scalars(
        select(Subject).where(Subject.id.in_(added | removed)).order_by(Subject.id)
    )
    groups: dict[str, list[dict[str, object]]] = {"added": [], "removed": []}
    for row in rows:
        snapshot = SubjectSnapshot.model_validate(row, from_attributes=True).model_dump(mode="json")
        key = "added" if row.id in added else "removed"
        candidate = {**groups, key: [*groups[key], snapshot], "reason": reason}
        if len(json.dumps(candidate, ensure_ascii=False).encode("utf-8")) > 3000:
            await record_event(
                session,
                "user.subjects_updated",
                actor_user_id,
                subject_user_id=user_id,
                data={**groups, "reason": reason},
            )
            groups = {"added": [], "removed": []}
        groups[key].append(snapshot)
    if groups["added"] or groups["removed"]:
        await record_event(
            session,
            "user.subjects_updated",
            actor_user_id,
            subject_user_id=user_id,
            data={**groups, "reason": reason},
        )
