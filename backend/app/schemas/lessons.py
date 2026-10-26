"""Bounded course contracts; no request can set ownership or trusted permission flags."""

import re
import unicodedata
from datetime import date, datetime
from typing import Literal, Self
from urllib.parse import parse_qs, urlsplit

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.auth import InputModel

LessonIcon = Literal[
    "book", "science", "calculator", "language", "history", "code", "school",
    "physics", "biology", "geology", "engineering", "astronomy", "statistics",
    "economics", "finance", "sociology", "geography", "philosophy", "literature",
    "ancient", "art", "music",
]
ElementKind = Literal["section", "subsection", "text", "youtube", "file", "table"]
ScheduleMode = Literal["inherit", "from", "range"]


def normalized_title(value: str) -> str:
    """Return a Unicode-normalized title with collapsed whitespace."""
    return " ".join(unicodedata.normalize("NFKC", value).split())


def youtube_id(value: str) -> str:
    """Extract a video ID from an exact HTTPS YouTube host without fetching remote URLs."""
    try:
        url = urlsplit(value)
        if url.scheme != "https" or url.username or url.password or url.port:
            raise ValueError
        host = url.hostname
        if host == "youtu.be":
            candidate = url.path.removeprefix("/")
        elif host in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
            if url.path == "/watch":
                values = parse_qs(url.query).get("v", [])
                candidate = values[0] if len(values) == 1 else ""
            else:
                match = re.fullmatch(r"/(?:embed|shorts)/([\w-]{11})", url.path)
                candidate = match[1] if match else ""
        else:
            raise ValueError
        if not re.fullmatch(r"[A-Za-z0-9_-]{11}", candidate):
            raise ValueError
        return candidate
    except ValueError:
        raise ValueError("Utilisez un lien HTTPS vers une vidéo YouTube valide.") from None


class LessonFields(InputModel):
    """Validate public course-card fields shared by creation and editing."""

    title: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=2000)
    subject_id: int = Field(gt=0)

    @field_validator("title", "description", mode="before")
    @classmethod
    def clean_text(cls, value: str) -> str:
        """Reject blank normalized metadata before database insertion."""
        if not isinstance(value, str):
            raise ValueError("Ce champ doit être du texte.")
        value = normalized_title(value)
        if not value:
            raise ValueError("Ce champ est obligatoire.")
        return value


class Versioned(InputModel):
    """Reject stale mutations instead of silently overwriting a collaborator's changes."""

    expected_version: int = Field(ge=0)


class LessonUpdate(LessonFields, Versioned):
    """Update metadata without allowing ownership reassignment."""


class ResponsibilityUpdate(Versioned):
    """Transfer management to an eligible teacher and optionally change the subject."""

    responsible_id: int = Field(gt=0)
    subject_id: int = Field(gt=0)


class ElementFields(InputModel):
    """Represent a section audience or independent media dates, normalized by the service."""

    title: str = Field(default="", max_length=200)
    body: str = Field(default="", max_length=3000)
    schedule_mode: ScheduleMode = "inherit"
    starts_on: date | None = None
    ends_on: date | None = None
    audience: Literal["students", "staff"] = "students"

    @field_validator("title", mode="before")
    @classmethod
    def clean_title(cls, value: str) -> str:
        """Trim element labels while preserving text-body whitespace."""
        if not isinstance(value, str):
            raise ValueError("Le titre doit être du texte.")
        return normalized_title(value)

    @model_validator(mode="after")
    def valid_schedule(self) -> Self:
        """Require dates only for explicit restrictions and reject reversed periods."""
        if self.schedule_mode == "inherit":
            valid = self.starts_on is None and self.ends_on is None
        elif self.schedule_mode == "from":
            valid = self.starts_on is not None and self.ends_on is None
        else:
            valid = (
                self.starts_on is not None
                and self.ends_on is not None
                and self.ends_on >= self.starts_on
            )
        if not valid:
            raise ValueError("La période sélectionnée est incomplète ou invalide.")
        return self


class ElementCreate(ElementFields, Versioned):
    """Create a typed element at the end of its authorized parent's children."""

    kind: ElementKind
    parent_id: int | None = Field(default=None, gt=0)
    row_index: int | None = Field(default=None, ge=0, le=19)
    column_index: int | None = Field(default=None, ge=0, le=5)
    table_rows: int = Field(default=1, ge=1, le=20)
    table_columns: list[str] = Field(
        default_factory=lambda: ["Colonne 1"], min_length=1, max_length=6
    )

    @field_validator("table_columns")
    @classmethod
    def clean_columns(cls, columns: list[str]) -> list[str]:
        """Accept arbitrary author-selected labels, bounded independently of their meaning."""
        labels = [normalized_title(label) for label in columns]
        if any(not label or len(label) > 100 for label in labels):
            raise ValueError("Chaque colonne nécessite un titre de 1 à 100 caractères.")
        return labels


class ElementUpdate(ElementFields, Versioned):
    """Edit content and dates while preserving its stable ID, type and parent."""


class ElementMove(Versioned):
    """Move one place among siblings using keyboard-accessible controls."""

    direction: Literal["up", "down"]


class TableChange(Versioned):
    """Change dynamic table structure without encoding pedagogical column names in SQL."""

    action: Literal["add_row", "remove_row", "add_column", "remove_column", "rename_column"]
    index: int = Field(default=0, ge=0, le=19)
    label: str = Field(default="", max_length=100)


class UploadCreate(ElementFields, Versioned):
    """Capture display properties and the target before accepting any binary bytes."""

    filename: str = Field(min_length=1, max_length=200)
    size_bytes: int = Field(gt=0, le=52428800)
    parent_id: int = Field(gt=0)
    element_id: int | None = Field(default=None, gt=0)
    row_index: int | None = Field(default=None, ge=0, le=19)
    column_index: int | None = Field(default=None, ge=0, le=5)


class FileResponse(BaseModel):
    """Expose file facts only after the containing element's authorization was checked."""

    id: int
    original_name: str
    extension: str
    media_type: str
    size_bytes: int
    sha256: str


class PromotionGrant(Versioned):
    """Allow optional dates or derive September through August from the promotion year."""

    starts_on: date | None = None
    ends_on: date | None = None

    @model_validator(mode="after")
    def valid_period(self) -> Self:
        """Reject partial or reversed overrides of the default school-year period."""
        if (self.starts_on is None) != (self.ends_on is None):
            raise ValueError("Renseignez les deux dates.")
        if self.starts_on and self.ends_on and self.ends_on < self.starts_on:
            raise ValueError("La fin doit suivre le début.")
        return self


class LessonPerson(BaseModel):
    """Expose only a staff display name, never private email or school-profile data."""

    id: int
    label: str
    role: Literal["user", "kholleur", "teacher", "admin"] | None = None
    can_edit: bool = False


class LessonCard(BaseModel):
    """Course metadata is visible in the catalogue even when page access is denied."""

    id: int
    title: str
    description: str
    icon: LessonIcon
    color: str
    creator: LessonPerson
    responsible: LessonPerson
    subject_id: int
    subject_name: str
    collaborators: list[LessonPerson] = Field(default_factory=list)
    can_open: bool
    can_edit: bool
    version: int
    updated_at: datetime


class ElementResponse(BaseModel):
    """Describe visible content or a media placeholder without exposing unavailable video URLs."""

    id: int
    parent_id: int | None
    kind: ElementKind
    position: int
    title: str
    body: str
    schedule_mode: ScheduleMode
    starts_on: date | None
    ends_on: date | None
    effective_starts_on: date | None
    effective_ends_on: date | None
    inherited_from: str | None
    available: bool
    status: Literal["available", "scheduled", "expired"]
    audience: Literal["students", "staff"] = "students"
    effective_audience: Literal["students", "staff"] = "students"
    table_rows: int = 1
    table_columns: list[str] = Field(default_factory=list)
    row_index: int | None = None
    column_index: int | None = None
    file: FileResponse | None = None


class LessonAccess(BaseModel):
    """Describe an editor-visible promotion grant without disclosing student rosters."""

    promotion_id: int
    identifier: str
    year: int
    color: str
    is_active: bool
    starts_on: date
    ends_on: date


class LessonDetail(LessonCard):
    """Return staff settings only to authorized editors."""

    can_view_statistics: bool = False

    can_manage_collaborators: bool
    can_transfer: bool = False
    staff_view: bool
    today: date
    elements: list[ElementResponse]
    promotions: list[LessonAccess] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class LessonPage(BaseModel):
    """Return a bounded searchable catalogue and the caller's creation capability."""

    items: list[LessonCard]
    total: int
    offset: int
    limit: int
    can_create: bool
