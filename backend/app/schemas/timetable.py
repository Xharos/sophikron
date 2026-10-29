"""Bounded timetable settings, recurring blocks and occurrence edits."""

from datetime import date
from typing import Annotated, Literal, Self

from pydantic import BaseModel, Field, model_validator

from app.schemas.auth import InputModel


class TimeBreak(InputModel):
    """Describe an excluded wall-clock interval, in seconds after midnight."""

    start: int = Field(ge=0, lt=86400, strict=True)
    end: int = Field(gt=0, le=86400, strict=True)


class Holiday(InputModel):
    """Exclude inclusive calendar dates from teaching and cycle advancement."""

    name: str = Field(default="Vacances", max_length=100)
    start: date
    end: date


class YearSettings(InputModel):
    """Configure a bounded school year and an exact half-session daily grid."""

    start: date
    end: date
    day_start: int = Field(default=28800, ge=0, lt=86400, strict=True)
    day_end: int = Field(default=68100, gt=0, le=86400, strict=True)
    session_minutes: int = Field(default=55, ge=10, le=240, strict=True)
    saturday: bool = False
    breaks: list[TimeBreak] = Field(
        default_factory=lambda: [
            TimeBreak(start=35400, end=36600),
            TimeBreak(start=57000, end=58200),
        ],
        max_length=8,
    )
    lunch_start: int = Field(default=43200, ge=0, lt=86400, strict=True)
    lunch_end: int = Field(default=50400, gt=0, le=86400, strict=True)
    holidays: list[Holiday] = Field(default_factory=list, max_length=40)

    @model_validator(mode="after")
    def valid_intervals(self) -> Self:
        """Reject reversed, overlapping or unbounded settings before grid expansion."""
        if not 0 <= (self.end - self.start).days <= 370 or self.day_end <= self.day_start:
            raise ValueError("Période scolaire ou horaires invalides.")
        previous = self.day_start
        for pause in sorted(self.breaks, key=lambda item: item.start):
            if not previous <= pause.start < pause.end <= self.day_end:
                raise ValueError(
                    "Les pauses doivent être ordonnées, distinctes et dans la journée."
                )
            previous = pause.end
        if any(item.end < item.start for item in self.holidays):
            raise ValueError("Une fin de vacances précède son début.")
        if not self.day_start <= self.lunch_start < self.lunch_end <= self.day_end:
            raise ValueError("Les horaires du self doivent rester dans la journée.")
        if self.lunch_end - self.lunch_start < self.session_minutes * 60:
            raise ValueError("Le self doit ouvrir pendant au moins une séance complète.")
        return self


class SessionFields(InputModel):
    """Describe a block independently of its civil date or weekly pattern."""

    start_slot: int = Field(default=0, ge=0, le=200, strict=True)
    duration_slots: int = Field(default=2, ge=1, le=100, strict=True)
    start_time: int | None = Field(default=None, ge=0, lt=86400, strict=True)
    end_time: int | None = Field(default=None, gt=0, le=86400, strict=True)
    subject_id: int | None = Field(default=None, gt=0, strict=True)
    teacher_id: int | None = Field(default=None, gt=0, strict=True)
    teacher_ids: list[Annotated[int, Field(gt=0, strict=True)]] = Field(
        default_factory=list, max_length=20
    )
    room_id: int | None = Field(default=None, gt=0, strict=True)
    kind: Literal["course", "td", "tp", "kholle"] = "course"
    title: str = Field(default="", max_length=150)
    target_kind: Literal["promotion", "halves", "thirds", "kholles", "custom", "student"] = (
        "promotion"
    )
    target_number: int | None = Field(default=None, ge=1, le=9223372036854775807, strict=True)
    target_user_id: int | None = Field(default=None, gt=0, strict=True)

    @model_validator(mode="before")
    @classmethod
    def normalize_teachers(cls, value: object) -> object:
        """Read legacy single assignments and keep the compatibility field consistent."""
        if isinstance(value, dict):
            value = dict(value)
            if "teacher_ids" not in value:
                value["teacher_ids"] = [value["teacher_id"]] if value.get("teacher_id") else []
            identifiers = value["teacher_ids"]
            if isinstance(identifiers, list):
                if all(type(item) is int for item in identifiers) and len(set(identifiers)) != len(
                    identifiers
                ):
                    raise ValueError("Un enseignant ne peut être affecté qu’une fois.")
                if value.get("teacher_id") not in (None, identifiers[0] if identifiers else None):
                    raise ValueError("Affectations enseignantes incohérentes.")
                value["teacher_id"] = identifiers[0] if identifiers else None
        return value

    @model_validator(mode="after")
    def valid_free_times(self) -> Self:
        """Require both exact boundaries and a positive uninterrupted free-time event."""
        if (self.start_time is None) != (self.end_time is None):
            raise ValueError("Saisissez le début et la fin de la séance en horaires libres.")
        if self.start_time is not None and self.end_time <= self.start_time:
            raise ValueError("La fin de la séance doit suivre son début.")
        return self

    @model_validator(mode="after")
    def valid_title(self) -> Self:
        """Require a meaningful custom title when no subject supplies an event label."""
        if self.subject_id is None and not self.title.strip():
            raise ValueError(
                "Saisissez un intitulé personnalisé lorsqu’aucune matière n’est sélectionnée."
            )
        return self

    @model_validator(mode="after")
    def valid_target(self) -> Self:
        """Reject ambiguous audience combinations before consulting promotion memberships."""
        group = self.target_kind in {"halves", "thirds", "kholles", "custom"}
        if group != (self.target_number is not None) or (self.target_kind == "student") != (
            self.target_user_id is not None
        ):
            raise ValueError("Destinataire de séance invalide.")
        if self.target_kind in {"halves", "thirds"} and self.target_number > (
            2 if self.target_kind == "halves" else 3
        ):
            raise ValueError("Choisissez A/B ou X/Y/Z.")
        if self.target_kind == "kholles" and self.target_number > 1000:
            raise ValueError("Numéro de groupe de khôlle invalide.")
        return self


class BlockFields(SessionFields):
    """Place an audience-scoped block on one actual school day."""

    starts_on: date


class SeriesFields(BlockFields):
    """Repeat on teaching weeks, with zero indicating a single occurrence."""

    interval: Literal[0, 1, 2, 3] = 1
    until: date | None = None


class SeriesData(SeriesFields):
    """Keep stable occurrence identities and isolated replacements or cancellations."""

    id: str = Field(pattern=r"^[0-9a-f]{32}$")
    lineage: str = Field(pattern=r"^[0-9a-f]{32}$")
    uid_lineage: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    uid_date: date | None = None
    exceptions: dict[date, BlockFields | None] = Field(default_factory=dict, max_length=100)


class YearDocument(BaseModel):
    """Serialize a compact annual document without copying encrypted member identities."""

    settings: YearSettings
    series: list[SeriesData] = Field(default_factory=list, max_length=5000)


class Version(InputModel):
    """Reject edits made against a stale calendar-year revision."""

    expected_revision: str = Field(pattern=r"^[0-9a-f]{32}$")
    confirmed_live: bool = False


class SettingsSave(Version):
    """Replace school-year settings after revalidating retained series."""

    settings: YearSettings


class PreferencesSave(Version):
    """Change the globally versioned automatic archive policy."""

    auto_archive: bool


class SeriesSave(Version):
    """Create a recurring block inside an annual calendar."""

    block: SeriesFields


class OccurrenceEdit(Version):
    """Change one source occurrence or split its series from that occurrence onward."""

    occurrence: date
    scope: Literal["one", "future"]
    block: SeriesFields | None = None


class EventPreview(Version):
    """Validate a proposed creation or occurrence edit without changing stored data."""

    series_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    occurrence: date | None = None
    scope: Literal["one", "future"] = "one"
    block: SeriesFields | None = None


class CalendarSave(InputModel):
    """Create or rename an agenda and manually choose its promotion."""

    name: str = Field(min_length=1, max_length=100)
    promotion_id: int | None = Field(default=None, gt=0, strict=True)
    expected_revision: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    is_paused: bool = True
    confirmed_live: bool = False
    confirmed_assignment: bool = False
    school_year: int | None = Field(default=None, ge=1900, le=9998, strict=True)
    settings: YearSettings | None = None


class SchoolYearCreate(InputModel):
    """Create an academic-year label independently of calendar configuration."""

    school_year: int = Field(ge=1900, le=9998, strict=True)


class CalendarRestore(Version):
    """Restore an archive, optionally releasing a promotion already used elsewhere."""

    detach_promotion: bool = False


class RoomSave(InputModel):
    """Create a shared room identified independently of its display name."""

    name: str = Field(min_length=1, max_length=80)
    expected_revision: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
