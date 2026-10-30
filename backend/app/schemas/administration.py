"""Validated promotion mutations and bounded dashboard response contracts."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.auth import AccountResponse, InputModel, UserResponse
from app.schemas.groups import GroupAssignment


class PromotionCreate(InputModel):
    """Create an active promotion using a year, identifier and hexadecimal CSS color."""

    year: int = Field(ge=1, le=9999)
    identifier: str = Field(min_length=1, max_length=64)
    color: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")

    @field_validator("identifier")
    @classmethod
    def validate_identifier(cls, value: str) -> str:
        """Trim the identifier and reject whitespace-only values."""
        value = value.strip()
        if not value:
            raise ValueError("Invalid identifier")
        return value

    @field_validator("color")
    @classmethod
    def normalize_color(cls, value: str) -> str:
        """Return a consistent uppercase CSS color."""
        return value.upper()


class PromotionUpdate(InputModel):
    """Update supplied fields, including reversible archive state; null is never a value."""

    year: int | None = Field(default=None, ge=1, le=9999)
    identifier: str | None = Field(default=None, min_length=1, max_length=64)
    color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    is_active: bool | None = None
    archive_students: bool = False
    acknowledge_student_impact: bool = False

    @field_validator("year", "identifier", "color", "is_active", mode="before")
    @classmethod
    def forbid_null(cls, value: object) -> object:
        """Distinguish omitted fields from forbidden explicit null values."""
        if value is None:
            raise ValueError("Null is not supported")
        return value

    @field_validator("identifier")
    @classmethod
    def validate_identifier(cls, value: str) -> str:
        """Apply the same identifier normalization as creation."""
        return PromotionCreate.validate_identifier(value)

    @field_validator("color")
    @classmethod
    def normalize_color(cls, value: str) -> str:
        """Apply the same color normalization as creation."""
        return value.upper()


class PromotionArchiveImpact(BaseModel):
    """Preview affected pupils without exposing their identities."""

    student_count: int
    accounts_to_disable: int
    blocked_count: int
    accounts_to_restore: int
    accounts_remaining_disabled: int


class TeamMember(BaseModel):
    """Expose only an administrator's staff directory identity and explicit roles."""

    id: int
    first_name: str
    last_name: str
    roles: list[str]


class TeamSubject(BaseModel):
    """Group active staff under one active subject, including empty groups."""

    id: int
    name: str
    icon: str
    color: str
    members: list[TeamMember]


class TeachingTeam(BaseModel):
    """Count unique staff accounts and role occurrences across active subjects."""

    subjects: list[TeamSubject]
    member_count: int
    teacher_count: int
    kholleur_count: int


class PromotionResponse(BaseModel):
    """Expose promotion metadata and the current number of linked permanent accounts."""

    id: int
    year: int
    identifier: str
    color: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
    member_count: int
    student_count: int = 0
    non_archived_student_count: int = 0
    teaching_count: int = 0
    archived_count: int = 0


class PromotionPage(BaseModel):
    """Return one ordered page with its filtered total."""

    items: list[PromotionResponse]
    total: int
    offset: int
    limit: int


class PromotionBadge(BaseModel):
    """Return personal memberships without disclosing promotion roster statistics."""

    id: int
    year: int
    identifier: str
    color: str
    is_active: bool


class DirectoryAccountResponse(UserResponse):
    """Extend only administrator directory responses with current saved group tags."""

    group_assignments: list[GroupAssignment] = Field(default_factory=list)
    promotions: list[PromotionBadge] = Field(default_factory=list)


class UserPage(BaseModel):
    """Return one ordered page of authorized account identities."""

    items: list[DirectoryAccountResponse]
    total: int
    offset: int
    limit: int


class SearchResult(BaseModel):
    """Expose only the identity needed to select a matching account."""

    id: int
    username: str
    first_name: str
    last_name: str
    status: str
    group_assignments: list[GroupAssignment] = Field(default_factory=list)
    roles: list[str] = Field(default_factory=list)
    promotions: list[PromotionBadge] = Field(default_factory=list)


class EventResponse(BaseModel):
    """Expose structured facts without copying personal identities into event storage."""

    id: int
    occurred_at: datetime
    event_type: str
    schema_version: int
    actor_user_id: int | None
    subject_user_id: int | None
    actor_role: Literal["admin", "teacher", "kholleur", "user"] | None
    subject_role: Literal["admin", "teacher", "kholleur", "user"] | None
    promotion_snapshot: PromotionCreate | None
    resource_type: str | None
    resource_id: int | None
    data: dict[str, object]
    actor_label: str | None = None
    subject_label: str | None = None
    resource_label: str | None = None
    actor_profile_available: bool = False
    subject_profile_available: bool = False


class EventTypeResponse(BaseModel):
    """Describe registered event types without querying the journal or exposing identities."""

    code: str
    family: str
    label: str
    icon: str
    message: str


class EventPage(BaseModel):
    """Use an opaque timestamp/ID cursor for descending chronological pagination."""

    items: list[EventResponse]
    next_cursor: str | None


class DashboardSummary(BaseModel):
    """Return aggregate counts excluding the temporary installation account."""

    total_accounts: int
    pending_accounts: int
    active_accounts: int
    archived_accounts: int
    total_promotions: int
    active_promotions: int
    active_subjects: int = 0
    archived_subjects: int = 0
    subject_teachers: int = 0
    total_lessons: int = 0
    kholleurs: int = 0


class AccountArchive(InputModel):
    """Set archive state without accepting arbitrary account fields."""

    archived: bool
    acknowledge_course_impact: bool = False


class MembershipBatch(InputModel):
    """Bound a multi-selection assignment to one atomic server-side operation."""

    user_ids: list[Annotated[int, Field(gt=0)]] = Field(min_length=1, max_length=100)


class InvitationState(BaseModel):
    """Describe the latest invitation without exposing any stored verifier."""

    status: str
    expires_at: datetime | None = None
    purpose: str | None = None


class AdminAccountResponse(AccountResponse):
    """Expose account activity and invitation status only to authorized administrators."""

    archived_at: datetime | None
    invitation: InvitationState
    group_assignments: list[GroupAssignment] = Field(default_factory=list)


class StudentResponse(BaseModel):
    """Expose the teacher's minimum student directory without email or security history."""

    id: int
    username: str
    first_name: str
    last_name: str
    status: str
    created_at: datetime
    promotions: list[PromotionResponse] = Field(default_factory=list)
    group_assignments: list[GroupAssignment] = Field(default_factory=list)


class StudentPage(BaseModel):
    """Return a bounded page of students sharing at least one teacher promotion."""

    items: list[StudentResponse]
    total: int
    offset: int
    limit: int
