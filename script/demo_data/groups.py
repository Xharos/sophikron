"""Promotion partitions and reproducible random German-option audiences."""

import random

from .client import Client
from .configuration import SeedError, Settings


def seed_groups(client: Client, settings: Settings, catalogue: dict) -> dict[str, dict]:
    """Create missing groups without overwriting previous memberships on a retry."""
    result = {}
    for index, cohort in enumerate(settings.classes()):
        path = f"/promotion-groups/{catalogue['promotions'][cohort.identifier]['id']}"
        state = client.request("GET", path)
        roster = sorted(student["id"] for student in state["students"])
        if len(roster) != settings.pupils_per_class:
            raise SeedError("Effectif de promotion inattendu ; aucun groupe remplacé.")
        saved = {partition["kind"]: partition for partition in state["partitions"]}
        for kind in ("halves", "thirds", "kholles"):
            existing = saved.get(kind)
            if existing:
                if (
                    sorted(pupil for group in existing["groups"] for pupil in group["student_ids"])
                    != roster
                ):
                    raise SeedError(
                        "Une répartition existante est incomplète ; corrigez-la avant de reprendre."
                    )
                continue
            version = {
                "expected_revision": None,
                "roster_ids": roster,
                "archived_ids": [],
                "target_size": settings.kholle_group_size,
            }
            draft = client.request("POST", f"{path}/{kind}/preview", version)
            client.request("PUT", f"{path}/{kind}", {**version, "groups": draft})
        selected = sorted(
            random.Random(settings.random_seed + index).sample(roster, settings.german_pupils)
        )
        custom = client.request("GET", path + "/custom/groups")
        german = next(
            (group for group in custom["groups"] if group["name"].casefold() == "allemand"),
            None,
        )
        if german is not None and sorted(german["student_ids"]) != selected:
            raise SeedError(
                "Le groupe Allemand existant diffère du tirage attendu. "
                "Utilisez un autre namespace ou la même graine."
            )
        if german is None:
            german = client.request(
                "PUT",
                path + "/custom/0",
                {
                    "name": "Allemand",
                    "student_ids": selected,
                    "expected_revision": None,
                    "x": 320,
                    "y": 20,
                },
            )
        result[cohort.identifier] = german
    return result
