"""Minute-based requirements for each group within an inclusive weekly period."""

from datetime import date
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from app.schemas.auth import InputModel


class KholleSubject(InputModel):
    """Require an exact nonnegative duration for each group in one subject."""

    subject_id: int = Field(gt=0, strict=True)
    minutes: int = Field(ge=0, le=600000, strict=True)


class KholleSettings(InputModel):
    """Bound a configuration by Monday and Friday, including both weeks."""

    start: date
    end: date
    subjects: list[KholleSubject] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def valid_period(self) -> Self:
        """Reject reversed periods, incorrect weekdays and duplicate subjects."""
        if self.start.weekday() != 0 or self.end.weekday() != 4 or self.end < self.start:
            raise ValueError("Choisissez un lundi de début et un vendredi de fin.")
        if len({item.subject_id for item in self.subjects}) != len(self.subjects):
            raise ValueError("Une matière ne peut être sélectionnée qu’une fois.")
        return self


class KholleSave(InputModel):
    """Protect configuration writes against concurrent agenda and holiday changes."""

    expected_revision: str
    expected_year_revision: str
    settings: KholleSettings


class KholleWishEntry(InputModel):
    """Keep zero explicit and use null to remove an unfilled commitment."""

    user_id: int = Field(gt=0, strict=True)
    subject_id: int = Field(gt=0, strict=True)
    sessions: int | None = Field(ge=0, le=1000, strict=True)


class KholleWishesSave(InputModel):
    """Submit the complete visible roster against its observed annual revision."""

    expected_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    entries: list[KholleWishEntry] = Field(max_length=10000)

    @model_validator(mode="after")
    def unique_entries(self) -> Self:
        """Reject repeated person/subject pairs before any database writes."""
        if len({(entry.user_id, entry.subject_id) for entry in self.entries}) != len(self.entries):
            raise ValueError("Un intervenant ne peut apparaître qu’une fois par matière.")
        return self


class KholleSubjectRooms(InputModel):
    """Select a nonempty set of existing rooms for one allocated subject."""

    subject_id: int = Field(gt=0, strict=True)
    room_ids: list[Annotated[int, Field(gt=0, strict=True)]] = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def unique_rooms(self) -> Self:
        """Reject repeated, noninteger or nonpositive room identities."""
        if any(type(room) is not int or room <= 0 for room in self.room_ids):
            raise ValueError("Sélectionnez des salles valides.")
        if len(set(self.room_ids)) != len(self.room_ids):
            raise ValueError("Une salle ne peut être sélectionnée qu’une fois par matière.")
        return self


class KholleTeacherPreference(InputModel):
    """Keep one annual assigned-promotion preference per teacher or kholleur."""

    user_id: int = Field(gt=0, strict=True)
    prefer_own_promotion: bool = Field(default=True, strict=True)


class KholloscopeValidate(InputModel):
    """Validate a milestone against observed inputs and the previous saved milestone."""

    expected_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    step: Literal["volumes", "wishes", "service"]
    rooms: list[KholleSubjectRooms] = Field(default_factory=list, max_length=200)
    teacher_preferences: list[KholleTeacherPreference] | None = Field(
        default=None, max_length=10000
    )
