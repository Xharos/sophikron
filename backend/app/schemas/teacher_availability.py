"""Bound the annual teacher availability editor independently of teaching sessions."""

from typing import Self

from pydantic import Field, model_validator

from app.schemas.auth import InputModel


class AvailabilityRange(InputModel):
    """Describe one weekday's available wall-clock interval, in seconds after midnight."""

    weekday: int = Field(ge=0, le=5, strict=True)
    start: int = Field(ge=0, lt=86400, strict=True)
    end: int = Field(gt=0, le=86400, strict=True)

    @model_validator(mode="after")
    def ordered(self) -> Self:
        """Reject empty and reversed intervals."""
        if self.end <= self.start:
            raise ValueError("La fin doit suivre le début de la disponibilité.")
        return self


class AvailabilitySave(InputModel):
    """Replace one annual pattern; null restores the default and an empty list closes all days."""

    expected_revision: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    ranges: list[AvailabilityRange] | None = Field(max_length=100)
