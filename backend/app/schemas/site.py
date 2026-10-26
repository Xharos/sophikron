"""Bounded administrator inputs and explicitly public site presentation contracts."""

from datetime import date
from typing import Annotated, Literal, Self

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.auth import InputModel
from app.schemas.lessons import LessonIcon, Versioned, normalized_title

Color = Annotated[str, Field(pattern=r"^#[0-9A-Fa-f]{6}$")]
Identifiers = Annotated[list[Annotated[int, Field(gt=0)]], Field(max_length=100)]


class SubjectFields(InputModel):
    """Validate a subject's shared identity without allowing arbitrary CSS or icon markup."""

    name: str = Field(min_length=1, max_length=100)
    icon: LessonIcon = "book"
    color: Color = "#244BC1"

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        """Normalize a nonempty label for display and duplicate checks."""
        value = normalized_title(value)
        if not value:
            raise ValueError("Le nom est obligatoire.")
        return value

    @field_validator("color")
    @classmethod
    def clean_color(cls, value: str) -> str:
        """Canonicalize the validated hexadecimal color."""
        return value.upper()


class SubjectUpdate(SubjectFields, Versioned):
    """Save one coherent identity revision."""


class SubjectResponse(SubjectFields):
    """Expose subject metadata and optional administrator aggregates."""

    id: int
    is_active: bool
    version: int
    teacher_count: int = 0
    lesson_count: int = 0


class SettingsFields(InputModel):
    """Accept only public site presentation, never secrets or deployment settings."""

    name: str = Field(min_length=1, max_length=100)
    home_text: str = Field(max_length=3000)
    text_color: Color = "#244BC1"
    holiday_color: Color = "#244BC1"

    _name = field_validator("name")(SubjectFields.clean_name)
    _colors = field_validator("text_color", "holiday_color")(SubjectFields.clean_color)


class SettingsUpdate(SettingsFields, Versioned):
    """Reject overwriting another administrator's site configuration."""


class SettingsResponse(SettingsFields):
    """Provide the live public identity and its editing revision."""

    version: int = 0


class TimelineFields(SubjectFields):
    """Validate inclusive calendar bounds for an annual bar."""

    icon: Literal["book"] = "book"
    starts_on: date
    ends_on: date

    @model_validator(mode="after")
    def period(self) -> Self:
        """Reject reversed inclusive periods."""
        if self.ends_on < self.starts_on:
            raise ValueError("La fin doit suivre le début.")
        return self


class TimelineUpdate(TimelineFields, Versioned):
    """Update a bar while detecting concurrent edits."""


class TimelineResponse(TimelineFields):
    """Expose an annual bar without any account or promotion references."""

    id: int
    version: int


class EventFields(TimelineFields):
    """Associate one event with an explicit nonempty set of bars."""

    kind: Literal["holiday", "oral", "written", "school", "other"] = "other"
    timeline_ids: Identifiers = Field(min_length=1)

    @field_validator("timeline_ids")
    @classmethod
    def unique_bars(cls, value: list[int]) -> list[int]:
        """Reject duplicate associations rather than failing during persistence."""
        if len(value) != len(set(value)):
            raise ValueError("Timeline dupliquée.")
        return value


class EventUpdate(EventFields, Versioned):
    """Save dates and all shared associations atomically."""


class EventResponse(EventFields):
    """Describe a public event and its shared bar references."""

    id: int
    version: int


class PublicSite(BaseModel):
    """Whitelist all content intentionally published on the public homepage."""

    settings: SettingsResponse
    timelines: list[TimelineResponse]
    events: list[EventResponse]
    today: date


class CourseImpact(BaseModel):
    """Identify managed courses before an administrator revokes teaching rights."""

    id: int
    title: str
    subject_id: int
    responsible: bool
