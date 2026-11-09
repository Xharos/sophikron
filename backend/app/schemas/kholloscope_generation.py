"""Bound administrator generation inputs and optimistic draft edits."""

from datetime import date
from typing import Literal, Self

from pydantic import Field, model_validator

from app.schemas.auth import InputModel


class GenerationRules(InputModel):
    """Configure whole-session rounding, adjacent-week recovery and staff lunch protection."""

    rounding: Literal["none", "floor", "ceil"] = "none"
    teacher_lunch: bool = Field(default=True, strict=True)
    teacher_lunch_minutes: int = Field(default=55, ge=20, le=120, strict=True)
    recovery_weeks: int = Field(default=1, ge=0, le=1, strict=True)
    max_per_day: int = Field(default=2, ge=1, le=4, strict=True)
    time_limit: int = Field(default=900, ge=5, le=43200, strict=True)
    preserve_locks: bool = Field(default=True, strict=True)
    optimize: bool = Field(default=False, strict=True)
    time_stability_percent: int = Field(default=5, ge=1, le=97, strict=True)
    time_weekly_percent: int = Field(default=15, ge=1, le=97, strict=True)
    time_rotation_percent: int = Field(default=75, ge=1, le=97, strict=True)
    time_annual_percent: int = Field(default=5, ge=1, le=97, strict=True)

    @model_validator(mode="after")
    def valid_time_distribution(self) -> Self:
        """Require positive stage shares totaling exactly one hundred percent."""
        if sum(self.time_distribution()) != 100:
            raise ValueError("La répartition du temps doit totaliser 100 %.")
        return self

    def time_distribution(self) -> tuple[int, int, int, int]:
        """Return initial percentages in solver stage order."""
        return (
            self.time_stability_percent,
            self.time_weekly_percent,
            self.time_rotation_percent,
            self.time_annual_percent,
        )

    @classmethod
    def from_saved_options(cls, options: dict) -> "GenerationRules":
        """Read saved rules, ignoring the retired A/B inversion option.

        Parameters
        ----------
        options
            Persisted options from an existing run, which may predate fixed A/B service.

        Returns
        -------
        GenerationRules
            Current validated rules without changing the stored run.
        """
        return cls.model_validate({k: v for k, v in options.items() if k != "balance_odd_cycles"})


class GenerationStart(InputModel):
    """Start against the observed preparation, course and availability revision."""

    expected_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    rules: GenerationRules


class DraftVersion(InputModel):
    """Prevent stale draft changes and publication."""

    expected_revision: str = Field(pattern=r"^[0-9a-f]{32}$")


class CancelGeneration(InputModel):
    """Cancel only the observed job, never a newer run started by another administrator."""

    run_id: str = Field(pattern=r"^[0-9a-f]{32}$")


class DraftMove(DraftVersion):
    """Move one anonymous session without altering its exact teacher or subject service."""

    session_id: str = Field(max_length=100)
    day: date
    start: int = Field(ge=0, lt=86400, strict=True)
    room_id: int = Field(gt=0, strict=True)
    locked: bool = Field(default=True, strict=True)


class GroupMapping(InputModel):
    """Bind one abstract track to a real numbered group after calendar generation."""

    calendar_id: int = Field(gt=0, strict=True)
    track: int = Field(gt=0, strict=True)
    group: int = Field(gt=0, strict=True)


class AssignGroups(DraftVersion):
    """Store a complete bijection; group memberships are never modified."""

    mappings: list[GroupMapping] | None = Field(default=None, max_length=10000)
    mode: Literal["fixed", "weekly", "cycle"] = "fixed"


class ApplyDraft(DraftVersion):
    """Explicitly confirm applying a fully assigned proposal to live calendars."""

    confirmed_live: bool = Field(default=False, strict=True)


class RemoveKholloscope(DraftVersion):
    """Confirm removal against both the run and the current live calendar revisions."""

    expected_source_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    scope: Literal["future", "all"] = "future"
    confirmation: str = Field(max_length=20)
