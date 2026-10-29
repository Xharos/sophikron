"""Dataset defaults and pure configuration checks; no credentials are stored here."""

import re
from calendar import monthrange
from dataclasses import dataclass, field
from datetime import date, timedelta


class SeedError(Exception):
    """Report a sanitized configuration or API failure."""


SUBJECTS = {
    "maths": ("Mathématiques", "#2563EB", "calculator"),
    "si": ("Sciences industrielles de l’ingénieur", "#7C3AED", "engineering"),
    "physics": ("Physique-chimie", "#E11D48", "physics"),
    "french": ("Français-philosophie", "#059669", "literature"),
    "english": ("Anglais", "#475569", "language"),
    "german": ("Allemand", "#B45309", "language"),
    "tipe": ("TIPE", "#BE185D", "science"),
    "computer_science": ("Informatique", "#0891B2", "code"),
}
# Inclusive exclusions: the official Monday resumption is never excluded.
# Source: https://www.education.gouv.fr/calendrier-scolaire-toutes-les-dates-des-cours-et-des-vacances-100148?annee=308
ZONE_C_2026 = (
    ("Toussaint", "2026-10-17", "2026-11-01"),
    ("Noël", "2026-12-19", "2027-01-03"),
    ("Hiver — zone C", "2027-02-06", "2027-02-21"),
    ("Printemps — zone C", "2027-04-03", "2027-04-18"),
    ("Ascension", "2027-05-06", "2027-05-07"),
    ("Été", "2027-07-03", "2027-08-31"),
)


@dataclass(frozen=True)
class ClassSpec:
    """Identify a promotion and its independent annual calendar."""

    identifier: str
    calendar_name: str
    color: str


@dataclass
class Settings:
    """Control sizes, staff, teaching hours and dates from the executable entry point."""

    school_year: int = 2026
    class_count: int = 2
    pupils_per_class: int = 45
    german_pupils: int = 10
    kholle_group_size: int = 3
    random_seed: int = 2026
    namespace: str = "demo"
    email_domain: str = "example.org"
    subject_prefix: str = ""
    filled_calendar_indexes: tuple[int, ...] = (0,)
    broadcast: bool = False
    include_summer_holidays: bool = True
    rooms: tuple[str, ...] = ("B208", "C105", "C106", "D202", "E301")
    holidays: tuple[tuple[str, str, str], ...] = ZONE_C_2026
    teacher_counts: dict[str, int] = field(
        default_factory=lambda: {
            "si": 2,
            "maths": 2,
            "physics": 2,
            "english": 1,
            "french": 1,
            "german": 1,
        }
    )
    kholleur_counts: dict[str, int] = field(
        default_factory=lambda: {
            "si": 1,
            "maths": 1,
            "physics": 1,
            "english": 1,
        }
    )
    weekly_hours: dict[str, dict[str, int]] = field(
        default_factory=lambda: {
            "maths": {"course": 6, "td": 3},
            "si": {"course": 2, "td": 2, "tp": 4},
            "physics": {"course": 5, "td": 1, "tp": 2},
            "english": {"course": 1, "td": 1},
            "computer_science": {"td": 1, "tp": 1},
            "french": {"course": 2},
        }
    )
    half_group_tp_subjects: tuple[str, ...] = ("si", "physics")
    german_option_hours: int = 0

    def classes(self) -> list[ClassSpec]:
        """Return the requested number of separately named PTSI/PT cohorts."""
        colors = ("#A34E18", "#244BC1", "#67449A", "#087E8B", "#C03654", "#786014")
        prefix = "" if self.namespace == "demo" else f"{self.namespace} · "
        return [
            ClassSpec(
                prefix
                + ("PTSI" if index % 2 == 0 else "PT")
                + (f"{index // 2 + 1}" if index > 1 else ""),
                prefix + f"{index + 1} année",
                colors[index % len(colors)],
            )
            for index in range(self.class_count)
        ]

    def calendar_settings(self) -> dict:
        """Bound the calendar by the first September Monday and last July Friday."""
        start = date(self.school_year, 9, 1)
        start += timedelta(days=(-start.weekday()) % 7)
        end = date(self.school_year + 1, 7, monthrange(self.school_year + 1, 7)[1])
        end -= timedelta(days=(end.weekday() - 4) % 7)
        return {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "day_start": 28800,
            "day_end": 68100,
            "session_minutes": 55,
            "saturday": False,
            "lunch_start": 43200,
            "lunch_end": 50400,
            "breaks": [{"start": 35400, "end": 36600}, {"start": 57000, "end": 58200}],
            "holidays": [
                {"name": name, "start": first, "end": last}
                for name, first, last in self.holidays
                if self.include_summer_holidays or name != "Été"
            ],
        }

    def validate(self) -> None:
        """Reject unusable scenarios before authentication or any persistent write."""
        if not re.fullmatch(r"[a-z0-9-]{1,24}", self.namespace):
            raise SeedError(
                "Le nom de scénario doit contenir 1 à 24 lettres minuscules, chiffres ou tirets."
            )
        if not 1 <= self.class_count <= 20 or not 1 <= self.pupils_per_class <= 2000:
            raise SeedError("Choisissez 1 à 20 classes et 1 à 2000 élèves par classe.")
        if not 1 <= self.german_pupils <= self.pupils_per_class:
            raise SeedError(
                "L’effectif allemand doit être compris entre 1 et l’effectif de classe."
            )
        if (
            not 2 <= self.kholle_group_size <= 5
            or not self.rooms
            or len(set(self.rooms)) != len(self.rooms)
        ):
            raise SeedError("Taille de groupe de khôlle ou salles invalides.")
        if any(index < 0 or index >= self.class_count for index in self.filled_calendar_indexes):
            raise SeedError("Indice d’agenda à remplir invalide.")
        if len(set(self.filled_calendar_indexes)) != len(self.filled_calendar_indexes):
            raise SeedError("Les agendas à remplir doivent être distincts.")
        for counts in (self.teacher_counts, self.kholleur_counts):
            if any(
                key not in SUBJECTS or type(count) is not int or not 0 <= count <= 100
                for key, count in counts.items()
            ):
                raise SeedError("Nombre d’enseignants ou matière invalide.")
        for key, kinds in self.weekly_hours.items():
            if key not in SUBJECTS or any(
                kind not in {"course", "td", "tp", "kholle"}
                or type(hours) is not int
                or not 0 <= hours <= 40
                for kind, hours in kinds.items()
            ):
                raise SeedError("Répartition hebdomadaire invalide.")
        if not 0 <= self.german_option_hours <= 5:
            raise SeedError("Volume d’option allemand invalide.")
        for _, first, last in self.holidays:
            if (
                not date(self.school_year, 9, 1)
                <= date.fromisoformat(first)
                <= date.fromisoformat(last)
                <= date(self.school_year + 1, 8, 31)
            ):
                raise SeedError("Adaptez les vacances à l’année scolaire configurée.")
