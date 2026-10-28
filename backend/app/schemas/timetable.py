"""Bounded timetable settings, recurring blocks and occurrence edits."""

from datetime import date
from typing import Literal, Self

from pydantic import AwareDatetime, BaseModel, Field, model_validator

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
    day_end: int = Field(default=61200, gt=0, le=86400, strict=True)
    session_minutes: int = Field(default=55, ge=10, le=240, strict=True)
    saturday: bool = False
    breaks: list[TimeBreak] = Field(default_factory=list, max_length=8)
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
        return self


class SessionFields(InputModel):
    """Describe a block independently of its civil date or weekly pattern."""

    start_slot: int = Field(ge=0, le=200, strict=True)
    duration_slots: int = Field(default=2, ge=1, le=100, strict=True)
    subject_id: int | None = Field(default=None, gt=0, strict=True)
    teacher_id: int | None = Field(default=None, gt=0, strict=True)
    room_id: int | None = Field(default=None, gt=0, strict=True)
    kind: Literal["course", "td", "tp", "kholle"] = "course"
    title: str = Field(default="", max_length=150)
    target_kind: Literal["promotion", "halves", "thirds", "kholles", "student"] = "promotion"
    target_number: int | None = Field(default=None, ge=1, le=1000, strict=True)
    target_user_id: int | None = Field(default=None, gt=0, strict=True)

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
        group = self.target_kind in {"halves", "thirds", "kholles"}
        if group != (self.target_number is not None) or (self.target_kind == "student") != (
            self.target_user_id is not None
        ):
            raise ValueError("Destinataire de séance invalide.")
        if self.target_kind in {"halves", "thirds"} and self.target_number > (
            2 if self.target_kind == "halves" else 3
        ):
            raise ValueError("Choisissez A/B ou X/Y/Z.")
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
    exceptions: dict[date, BlockFields | None] = Field(default_factory=dict, max_length=100)
    template_key: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    cycle_phase: int | None = Field(default=None, ge=1, le=3, strict=True)
    uid_date: date | None = None
    first_uid: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")


class YearDocument(BaseModel):
    """Serialize a published version without copying encrypted member identities."""

    settings: YearSettings
    series: list[SeriesData] = Field(default_factory=list, max_length=5000)


class Version(InputModel):
    """Reject edits made against a stale calendar-year revision."""

    expected_revision: str = Field(pattern=r"^[0-9a-f]{32}$")


class SettingsSave(Version):
    """Replace school-year settings after revalidating retained series."""

    settings: YearSettings


class SeriesSave(Version):
    """Create a recurring block inside the administrator's draft."""

    block: SeriesFields


class OccurrenceEdit(Version):
    """Change one source occurrence or split its series from that occurrence onward."""

    occurrence: date
    scope: Literal["one", "future"]
    block: SeriesFields | None = None


class CalendarSave(InputModel):
    """Create or rename an agenda and manually choose its promotion."""

    name: str = Field(min_length=1, max_length=100)
    promotion_id: int | None = Field(default=None, gt=0, strict=True)
    expected_revision: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    is_paused: bool = False


class RoomSave(InputModel):
    """Create a shared room identified independently of its display name."""

    name: str = Field(min_length=1, max_length=80)
    expected_revision: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")


class YearCreate(InputModel):
    """Create a new annual draft, optionally reusing the preceding year's model."""

    settings: YearSettings
    copy_previous: bool = True


class CommonSettingsSave(InputModel):
    """Protect establishment-wide settings from stale concurrent replacements."""

    expected_revision: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    settings: YearSettings


class TemplateBlock(SessionFields):
    """Keep a stable weekly block identity across successive effective versions."""

    key: str = Field(pattern=r"^[0-9a-f]{32}$")
    weekday: int = Field(ge=0, le=5, strict=True)
    interval: Literal[1, 2, 3] = 1
    phase: int = Field(default=1, ge=1, le=3, strict=True)

    @model_validator(mode="after")
    def valid_phase(self) -> Self:
        """Keep cycle phase within the selected recurrence interval."""
        if self.phase > self.interval:
            raise ValueError("Phase hors du cycle choisi.")
        return self


class TemplateSave(Version):
    """Append an effective weekly version without overwriting dated exceptions."""

    effective_on: date | None = None
    effective_at: AwareDatetime | None = None
    acknowledge_history: bool = False
    blocks: list[TemplateBlock] = Field(max_length=250)

    @model_validator(mode="after")
    def unique_keys(self) -> Self:
        """Reject duplicated block identities that would produce ambiguous occurrence UIDs."""
        if len({block.key for block in self.blocks}) != len(self.blocks):
            raise ValueError("Blocs de semaine type dupliqués.")
        if self.effective_on is not None and self.effective_at is not None:
            raise ValueError("Choisissez une seule date d’application.")
        if any(
            block.kind == "kholle" or block.target_kind not in {"promotion", "halves", "thirds"}
            for block in self.blocks
        ):
            raise ValueError(
                "La semaine type accepte cours, TD et TP pour la classe, A/B ou X/Y/Z."
            )
        return self
