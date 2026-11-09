"""Bound private revision commands and explicit Monday merge confirmation."""

from datetime import date
from typing import Annotated, Self

from pydantic import Field, field_validator, model_validator

from app.schemas.auth import InputModel
from app.schemas.kholloscope_generation import DraftVersion, GenerationRules


class RevisionCreate(InputModel):
    """Fork the live calendar for one subject without altering published wishes."""

    expected_source_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    subject_id: int | None = Field(default=None, gt=0, strict=True)
    subject_ids: list[Annotated[int, Field(gt=0, strict=True)]] | None = Field(
        default=None, min_length=1, max_length=1000
    )
    effective_on: date
    return_on: date | None = None

    @model_validator(mode="after")
    def valid_return(self) -> Self:
        """Require a Monday return strictly after departure when a leave is temporary."""
        if self.return_on is not None and (
            self.return_on.weekday() != 0 or self.return_on <= self.effective_on
        ):
            raise ValueError("Le retour doit être un lundi après la prise d'effet.")
        return self

    @field_validator("effective_on")
    @classmethod
    def monday_only(cls, value: date) -> date:
        """Return the selected Monday or reject a partial-week boundary."""
        if value.weekday() != 0:
            raise ValueError("La prise d'effet doit être un lundi à minuit (Europe/Paris).")
        return value


class RevisionWish(InputModel):
    """Set a nonnegative future service weight in the subject's existing cycle unit."""

    user_id: int = Field(gt=0, strict=True)
    subject_id: int | None = Field(default=None, gt=0, strict=True)
    sessions: int = Field(ge=0, le=1000, strict=True)


class RevisionCalculate(DraftVersion):
    """Save branch wishes and queue a complete repair, with optional slot changes."""

    wishes: list[RevisionWish] = Field(max_length=1000)
    allow_moves: bool = Field(default=False, strict=True)
    rules: GenerationRules = Field(default_factory=GenerationRules)
    effective_on: date | None = None
    rooms: dict[str, list[Annotated[int, Field(gt=0, strict=True)]]] | None = None


class RevisionMerge(DraftVersion):
    """Require confirmation of both live publication and the exact effective date."""

    effective_on: date
    return_on: date | None = None
    confirmed_live: bool = Field(default=False, strict=True)


class RevisionRollback(DraftVersion):
    """Identify a future published revision and its observed concurrency token."""

    revision_id: str = Field(pattern=r"^[0-9a-f]{32}$")


class RevisionRoomChange(InputModel):
    """Preview or confirm a room replacement without changing any session time."""

    expected_source_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    room_id: int = Field(gt=0, strict=True)
    replacement_room_id: int = Field(gt=0, strict=True)
    starts_on: date
    subject_ids: list[Annotated[int, Field(gt=0, strict=True)]] = Field(
        min_length=1, max_length=1000
    )
    confirmed_live: bool = Field(default=False, strict=True)
