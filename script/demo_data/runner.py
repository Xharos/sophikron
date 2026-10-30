"""Assemble and validate a demo scenario, then execute resumable API-only stages."""

from .catalog import preflight, seed_catalog
from .client import Client
from .configuration import SUBJECTS, Settings
from .groups import seed_groups
from .identities import build_people
from .planning import build_plan
from .timetables import seed_timetables


def prepare(settings: Settings) -> tuple:
    """Validate and build all deterministic data without contacting any service."""
    settings.validate()
    pupils, staff = build_people(settings)
    plan = build_plan(settings, staff)
    return pupils, staff, plan


def describe(settings: Settings) -> None:
    """Print a reviewable scenario summary without credentials or personal account links."""
    pupils, staff, plan = prepare(settings)
    print(
        f"{settings.class_count} promotions ; {len(pupils)} élèves distincts ; "
        f"{sum(person.role == 'teacher' for person in staff)} professeurs ; "
        f"{sum(person.role == 'kholleur' for person in staff)} khôlleurs."
    )
    dates = settings.calendar_settings()
    print(
        f"Année {settings.school_year}/{settings.school_year + 1} : "
        f"{dates['start']} → {dates['end']}."
    )
    for key, kinds in settings.weekly_hours.items():
        print(f"  {SUBJECTS[key][0]} : {sum(kinds.values())} h/élève/semaine ({kinds}).")
    print(
        f"{len(plan)} séries hebdomadaires ; TP A/B sur les mêmes jours ; "
        "aucun cours pendant le self."
    )
    print(
        "Les semaines écourtées par les vacances ont un volume réel réduit ; "
        "les totaux annuels suivent les dates effectives."
    )


def seed(client: Client, settings: Settings) -> dict:
    """Create the reviewed scenario without deleting, replacing or inviting existing accounts."""
    pupils, staff, plan = prepare(settings)
    state = preflight(client, settings, pupils, staff)
    catalogue = seed_catalog(client, settings, pupils, staff, state)
    groups = seed_groups(client, settings, catalogue)
    calendars = seed_timetables(client, settings, catalogue, groups, plan)
    print("Scénario prêt. Comptes en attente d’activation ; aucun courriel envoyé.")
    return {**catalogue, "groups": groups, "calendars": calendars}
