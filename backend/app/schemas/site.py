"""Bounded administrator inputs and explicitly public site presentation contracts."""

from typing import Annotated

from pydantic import BaseModel, Field, field_validator

from app.schemas.auth import InputModel
from app.schemas.lessons import LessonIcon, Versioned, normalized_title

Color = Annotated[str, Field(pattern=r"^#[0-9A-Fa-f]{6}$")]


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

    _name = field_validator("name")(SubjectFields.clean_name)
    _colors = field_validator("text_color")(SubjectFields.clean_color)


class SettingsUpdate(SettingsFields, Versioned):
    """Reject overwriting another administrator's site configuration."""


class SettingsResponse(SettingsFields):
    """Provide the live public identity and its editing revision."""

    version: int = 0


class PublicSite(BaseModel):
    """Whitelist all content intentionally published on the public homepage."""

    settings: SettingsResponse


class CourseImpact(BaseModel):
    """Identify managed courses before an administrator revokes teaching rights."""

    id: int
    title: str
    subject_id: int
    responsible: bool
