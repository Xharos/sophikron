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
    """Patch annual ranges and integer kholle bounds; null ranges restore opening hours."""

    expected_revision: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    ranges: list[AvailabilityRange] | None = Field(default=None, max_length=100)
    kholle_min_hours: int | None = Field(default=None, ge=0, le=2147483647, strict=True)
    kholle_max_hours: int | None = Field(default=None, ge=0, le=2147483647, strict=True)

    @model_validator(mode="after")
    def valid_patch(self) -> Self:
        """Require both ordered hour bounds together and at least one annual change."""
        bounds = {"kholle_min_hours", "kholle_max_hours"}
        supplied = self.model_fields_set & bounds
        if supplied:
            if supplied != bounds or self.kholle_min_hours is None or self.kholle_max_hours is None:
                raise ValueError("Renseignez les deux bornes horaires.")
            if self.kholle_max_hours < self.kholle_min_hours:
                raise ValueError("Le maximum doit être supérieur ou égal au minimum.")
        elif "ranges" not in self.model_fields_set:
            raise ValueError("Aucune modification fournie.")
        return self
