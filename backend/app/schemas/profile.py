"""Validated private school profiles and explicit, bounded editing contracts."""

import re
from datetime import date
from typing import Annotated

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.identity import normalize_name
from app.core.security import normalize_email
from app.schemas.administration import PromotionBadge
from app.schemas.auth import InputModel, RoleCodes

Grade = Annotated[float, Field(ge=0, le=20, allow_inf_nan=False)]
PRIVATE_PROFILE_FIELDS = (
    "birth_date",
    "city",
    "postal_code",
    "commune_code",
    "previous_school",
    "baccalaureate",
    "orientation_project",
    "phone",
    "reference_adult",
)


def normalize_phone(value: str) -> str:
    """Normalize French national or international phone numbers without network requests."""
    compact = re.sub(r"[\s().-]", "", value.strip())
    if compact.startswith("00"):
        compact = "+" + compact[2:]
    if re.fullmatch(r"0[1-9][0-9]{8}", compact):
        compact = "+33" + compact[1:]
    if not re.fullmatch(r"\+[1-9][0-9]{6,14}", compact):
        raise ValueError("Invalid phone number")
    return compact


class BacSubject(InputModel):
    """Record a chosen option or specialty and its optional mark out of twenty."""

    name: str = Field(min_length=1, max_length=100)
    grade: Grade | None = None

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        """Reject blank subject labels while preserving educational punctuation."""
        value = " ".join(value.split())
        if not value:
            raise ValueError("Empty subject")
        return value


class Baccalaureate(InputModel):
    """Store the obtained diploma, overall mark and selected subjects together."""

    label: str | None = Field(default=None, max_length=100)
    year: int | None = Field(default=None, ge=1900)
    overall_grade: Grade | None = None
    subjects: list[BacSubject] = Field(default_factory=list, max_length=20)

    @field_validator("year")
    @classmethod
    def past_year(cls, value: int | None) -> int | None:
        """Reject a future year for a diploma already obtained."""
        if value is not None and value > date.today().year:
            raise ValueError("Future graduation year")
        return value

    @model_validator(mode="after")
    def unique_subjects(self) -> "Baccalaureate":
        """Avoid duplicate subjects that would make a student's marks ambiguous."""
        names = [subject.name.casefold() for subject in self.subjects]
        if len(names) != len(set(names)):
            raise ValueError("Duplicate subjects")
        return self


class ReferenceAdult(InputModel):
    """Record one designated adult's identity and contact phone."""

    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    phone: str = Field(min_length=1, max_length=40)

    _names = field_validator("first_name", "last_name")(normalize_name)
    _phone = field_validator("phone")(normalize_phone)


class SchoolProfile(InputModel):
    """Keep all newly collected personal fields optional and explicitly clearable."""

    birth_date: date | None = None
    city: str | None = Field(default=None, max_length=200)
    postal_code: str | None = Field(default=None, pattern=r"^[0-9]{5}$")
    commune_code: str | None = Field(default=None, pattern=r"^[0-9A-Z]{5}$")
    previous_school: str | None = Field(default=None, max_length=200)
    baccalaureate: Baccalaureate | None = None
    orientation_project: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=40)
    reference_adult: ReferenceAdult | None = None

    @field_validator("birth_date")
    @classmethod
    def past_birth_date(cls, value: date | None) -> date | None:
        """Reject future birthdays while storing no derived age."""
        if value is not None and value > date.today():
            raise ValueError("Future birth date")
        return value

    @field_validator("phone")
    @classmethod
    def valid_phone(cls, value: str | None) -> str | None:
        """Normalize a supplied phone or keep its explicit absence."""
        return normalize_phone(value) if value else None

    @field_validator("city", "previous_school", "orientation_project")
    @classmethod
    def clean_text(cls, value: str | None) -> str | None:
        """Trim optional text and reject invisible control characters."""
        if value is None:
            return None
        if any(ord(character) < 32 and character not in "\n\r\t" for character in value):
            raise ValueError("Invalid control character")
        return " ".join(value.split()) or None


class AdminProfileUpdate(SchoolProfile):
    """Patch identity, profile and explicit roles atomically, preserving the username."""

    expected_version: int = Field(ge=0)
    first_name: str | None = Field(default=None, min_length=1, max_length=100)
    last_name: str | None = Field(default=None, min_length=1, max_length=100)
    email: str | None = Field(default=None, min_length=3, max_length=254)
    roles: RoleCodes | None = None
    subject_ids: list[Annotated[int, Field(gt=0)]] | None = Field(default=None, max_length=100)
    acknowledge_course_impact: bool = False

    @field_validator("subject_ids")
    @classmethod
    def unique_subjects(cls, value: list[int] | None) -> list[int]:
        """Require an explicit unique assignment when the field is supplied."""
        if value is None or len(value) != len(set(value)):
            raise ValueError("Invalid subject assignments")
        return value

    @field_validator("roles", mode="before")
    @classmethod
    def required_roles(cls, value: object) -> object:
        """Allow omitted grants while rejecting an explicit null role assignment.

        Parameters
        ----------
        value
            The supplied role assignment before list validation.

        Returns
        -------
        object
            The non-null assignment for the shared role validator.
        """
        if value is None:
            raise ValueError("Roles cannot be null")
        return value

    @field_validator("first_name", "last_name", "email", mode="before")
    @classmethod
    def required_identity(cls, value: object) -> object:
        """Reject explicit null identities while allowing an omitted patch field."""
        if value is None:
            raise ValueError("Identity cannot be empty")
        return value

    _names = field_validator("first_name", "last_name")(normalize_name)
    _email = field_validator("email")(normalize_email)


class OrientationUpdate(InputModel):
    """Accept exactly the teacher-editable field and a concurrency version."""

    expected_version: int = Field(ge=0)
    orientation_project: str | None = Field(max_length=200)

    @field_validator("orientation_project")
    @classmethod
    def clean_orientation(cls, value: str | None) -> str | None:
        """Apply the same text normalization as administrator profile edits."""
        return SchoolProfile.clean_text(value)


class FullProfile(BaseModel):
    """Return private details only to the owner or an explicitly authorized staff member."""

    id: int
    username: str
    first_name: str
    last_name: str
    email: str
    roles: list[str]
    status: str
    profile_version: int
    profile: SchoolProfile
    age: int | None
    promotions: list[PromotionBadge]
    can_edit_all: bool
    can_edit_orientation: bool
    subject_ids: list[int] = Field(default_factory=list)
