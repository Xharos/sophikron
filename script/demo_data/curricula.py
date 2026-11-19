"""Seed the scenario programme and its supplied industrial sciences graph."""

from .client import Client
from .configuration import SeedError, Settings

SI_TREE = (
    (
        "Analyser",
        (
            "Analyser le besoin et les exigences",
            "Définir les frontières de l'analyse",
            "Analyser l'organisation fonctionnelle et structurelle",
            "Analyser les performances et les écarts",
            "Analyser un compromis produit-procédés-matériaux",
        ),
    ),
    (
        "Modéliser",
        (
            "Choisir les grandeurs physiques et les caractériser",
            "Proposer un modèle de connaissance et de comportement",
            "Valider un modèle",
        ),
    ),
    (
        "Résoudre",
        (
            "Proposer une démarche de résolution",
            "Mettre en œuvre une démarche de résolution analytique",
            "Mettre en œuvre une démarche de résolution numérique",
        ),
    ),
    (
        "Expérimenter",
        (
            "Mettre en œuvre un système",
            "Proposer et justifier un protocole expérimental",
            "Mettre en œuvre un protocole expérimental",
        ),
    ),
    (
        "Communiquer",
        (
            "Rechercher et traiter des informations",
            "Produire et échanger de l'information",
        ),
    ),
    (
        "Concevoir",
        (
            "Concevoir l'architecture d'un système innovant",
            "Proposer et choisir des solutions techniques",
            "Dimensionner une solution technique choisie",
        ),
    ),
    (
        "Réaliser",
        (
            "Réaliser tout ou partie d'un prototype",
            "Industrialiser un produit",
        ),
    ),
)


def si_document(subject_name: str) -> dict:
    """Build a portable graph with file-local IDs and stable sibling positions."""
    nodes = []
    for root_position, (name, children) in enumerate(SI_TREE):
        root_id = len(nodes) + 1
        nodes.append({"id": root_id, "name": name, "position": root_position, "parent_ids": []})
        for position, child in enumerate(children):
            nodes.append(
                {
                    "id": len(nodes) + 1,
                    "name": child,
                    "position": position,
                    "parent_ids": [root_id],
                }
            )
    return {
        "format": "sophikron.competencies",
        "version": 1,
        "subject_name": subject_name,
        "nodes": nodes,
    }


def seed_curriculum(client: Client, settings: Settings, subjects: dict[str, dict]) -> dict | None:
    """Create or extend the programme and return its SI graph when requested."""
    requested = settings.curriculum_subjects
    if not requested:
        return None
    title = f"Référentiel PTSI/PT · {settings.namespace}"
    catalog = client.request("GET", "/curricula/catalog")
    matches = [item for item in catalog["curricula"] if item["title"] == title]
    if len(matches) > 1:
        raise SeedError(f"Plusieurs référentiels portent le titre « {title} ».")
    subject_ids = [subjects[key]["id"] for key in requested]
    if matches:
        curriculum = matches[0]
        if not curriculum["is_active"]:
            raise SeedError(f"Le référentiel « {title} » est archivé.")
        missing = [key for key in subject_ids if key not in curriculum["subject_ids"]]
        if missing:
            curriculum = client.request(
                "PUT",
                f"/curricula/{curriculum['id']}",
                {
                    "title": title,
                    "description": curriculum["description"],
                    "source_url": curriculum["source_url"],
                    "is_active": curriculum["is_active"],
                    "subject_ids": [*curriculum["subject_ids"], *missing],
                    "expected_version": curriculum["version"],
                },
            )
    else:
        curriculum = client.request(
            "POST", "/curricula", {"title": title, "subject_ids": subject_ids}
        )
    print(f"Référentiel « {title} » disponible.")
    if "si" not in requested:
        return None
    subject = subjects["si"]
    path = f"/curricula/{curriculum['id']}/subjects/{subject['id']}"
    graph = client.request("GET", path)
    if graph["nodes"]:
        print("Le graphe SI existant est conservé.")
    else:
        graph = client.request(
            "POST",
            path + "/import",
            {
                "expected_version": graph["version"],
                "document": si_document(subject["name"]),
            },
        )
        print("Arborescence SI importée.")
    return graph
