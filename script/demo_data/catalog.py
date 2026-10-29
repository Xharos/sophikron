"""Safe account/catalogue creation and preflight checks for resumable API seeding."""

from .client import Client
from .configuration import SUBJECTS, SeedError, Settings
from .identities import Person


def preflight(
    client: Client, settings: Settings, pupils: list[Person], staff: list[Person]
) -> dict:
    """Reject conflicting identities and populated foreign promotions before writing anything."""
    users = {item["email"]: item for item in client.pages("/admin/users")}
    promotions = {
        item["identifier"]: item
        for item in client.pages("/admin/promotions", {"year": settings.school_year})
    }
    for person in [*pupils, *staff]:
        account = users.get(person.email)
        if account and (
            account["first_name"] != person.first_name
            or account["last_name"] != person.last_name
            or account["roles"] != [person.role]
            or account["status"] == "disabled"
        ):
            raise SeedError(
                "Une identité existe avec d’autres noms, rôles ou un statut archivé. "
                "Utilisez un autre namespace."
            )
    for cohort in settings.classes():
        promotion = promotions.get(cohort.identifier)
        if promotion is None:
            continue
        if not promotion["is_active"]:
            raise SeedError("Une promotion attendue est archivée ; choisissez un autre namespace.")
        roster = client.request("GET", f"/promotion-groups/{promotion['id']}")["students"]
        expected = {
            users[person.email]["id"]
            for person in pupils
            if person.promotion == cohort.identifier and person.email in users
        }
        if not {student["id"] for student in roster} <= expected:
            raise SeedError(
                "Une promotion contient d’autres élèves. Choisissez un nouveau namespace ; "
                "aucun élève existant n’est supprimé."
            )
    return {"users": users, "promotions": promotions}


def seed_catalog(
    client: Client,
    settings: Settings,
    pupils: list[Person],
    staff: list[Person],
    state: dict,
) -> dict:
    """Create missing catalogues/accounts and complete compatible staff subject assignments."""
    promotions = {}
    for cohort in settings.classes():
        promotion = state["promotions"].get(cohort.identifier)
        if promotion is None:
            promotion = client.request(
                "POST",
                "/admin/promotions",
                {
                    "identifier": cohort.identifier,
                    "year": settings.school_year,
                    "color": cohort.color,
                },
            )
        promotions[cohort.identifier] = promotion
    catalogue = [
        *client.pages("/admin/subjects"),
        *client.pages("/admin/subjects", {"is_active": "false"}),
    ]
    by_name = {item["name"].casefold(): item for item in catalogue}
    colors = {item["color"].upper() for item in catalogue}
    subjects = {}
    for key, (name, color, icon) in SUBJECTS.items():
        name = settings.subject_prefix + name
        item = by_name.get(name.casefold())
        if item and not item["is_active"]:
            raise SeedError("Une matière attendue est archivée ; réactivez-la avant de reprendre.")
        if item is None:
            number = int(color[1:], 16)
            while color in colors:
                number = (number + 0x473B61) % 0x1000000
                color = f"#{number:06X}"
            item = client.request(
                "POST", "/admin/subjects", {"name": name, "color": color, "icon": icon}
            )
            colors.add(color)
        subjects[key] = item
    users = dict(state["users"])
    for person in [*pupils, *staff]:
        promotion_ids = (
            [promotions[person.promotion]["id"]]
            if person.promotion
            else [item["id"] for item in promotions.values()]
        )
        account = users.get(person.email)
        if account is None:
            account = client.request(
                "POST",
                "/admin/users",
                {
                    "first_name": person.first_name,
                    "last_name": person.last_name,
                    "email": person.email,
                    "roles": [person.role],
                    "promotion_ids": promotion_ids,
                },
            )
            users[person.email] = account
        profile = client.request("GET", f"/admin/users/{account['id']}/profile")
        current_promotions = {item["id"] for item in profile["promotions"]}
        for identifier in promotion_ids:
            if identifier not in current_promotions:
                client.request("PUT", f"/admin/users/{account['id']}/promotions/{identifier}")
        if person.subjects:
            expected = {subjects[key]["id"] for key in person.subjects}
            assigned = set(profile["subject_ids"])
            if not assigned <= expected:
                raise SeedError(
                    "Un professeur possède d’autres matières. Aucun remplacement effectué."
                )
            if assigned != expected:
                client.request(
                    "PATCH",
                    f"/admin/users/{account['id']}/profile",
                    {
                        "expected_version": profile["profile_version"],
                        "subject_ids": sorted(expected),
                    },
                )
    print(
        f"{len(promotions)} promotions, {len(pupils)} élèves, "
        f"{len(staff)} personnels, {len(subjects)} matières prêts."
    )
    return {"promotions": promotions, "subjects": subjects, "users": users}
