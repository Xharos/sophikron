"""Deterministic synthetic identities, with distinct pupil and staff name pools."""

import unicodedata
from dataclasses import dataclass

from .configuration import SeedError, Settings

FIRST_NAMES = [
    "Alice",
    "Benoît",
    "Camille",
    "Diane",
    "Émile",
    "Farah",
    "Gabriel",
    "Héloïse",
    "Idriss",
    "Juliette",
    "Karim",
    "Louise",
    "Mathis",
    "Nora",
    "Oscar",
    "Pauline",
    "Quentin",
    "Romane",
    "Samuel",
    "Théo",
    "Ulysse",
    "Valentine",
    "William",
    "Xavière",
    "Yasmine",
    "Zoé",
    "Adrien",
    "Bérénice",
    "Clément",
    "Daphné",
    "Élodie",
    "Félix",
    "Garance",
    "Hugo",
    "Inès",
    "Jeanne",
    "Kévin",
    "Léa",
    "Maxime",
    "Noémie",
    "Olivier",
    "Perrine",
    "Raphaël",
    "Sarah",
    "Tristan",
    "Victoire",
    "Yanis",
    "Agathe",
    "Bastien",
    "Célia",
    "Damien",
    "Élise",
    "Florian",
    "Guillaume",
    "Hortense",
    "Iris",
    "Joachim",
    "Laurine",
    "Maëlle",
    "Nathan",
    "Océane",
    "Pierre",
    "Rémi",
    "Solène",
    "Timothée",
    "Violette",
    "Xavier",
    "Anaïs",
    "Baptiste",
    "Chloé",
    "Delphine",
    "Estelle",
    "Fabien",
    "Grégoire",
    "Hélène",
    "Isaac",
    "Joséphine",
    "Lucie",
    "Margaux",
    "Nicolas",
    "Ophélie",
    "Romain",
    "Salomé",
    "Thomas",
    "Vanessa",
    "Walid",
    "Axel",
    "Brice",
    "Coralie",
    "Denis",
]

LAST_NAMES = [
    "Martin",
    "Bernard",
    "Thomas",
    "Petit",
    "Robert",
    "Richard",
    "Durand",
    "Dubois",
    "Moreau",
    "Laurent",
    "Simon",
    "Michel",
    "Lefebvre",
    "Leroy",
    "Roux",
    "David",
    "Bertrand",
    "Morel",
    "Fournier",
    "Girard",
    "Bonnet",
    "Dupont",
    "Lambert",
    "Fontaine",
    "Rousseau",
    "Vincent",
    "Muller",
    "Lefevre",
    "Faure",
    "Andre",
    "Mercier",
    "Blanc",
    "Guerin",
    "Boyer",
    "Garnier",
    "Chevalier",
    "Francois",
    "Legrand",
    "Gauthier",
    "Garcia",
    "Perrin",
    "Robin",
    "Clement",
    "Morin",
    "Nicolas",
    "Henry",
    "Roussel",
    "Mathieu",
    "Gautier",
    "Masson",
    "Marchand",
    "Duval",
    "Denis",
    "Dumont",
    "Marie",
    "Lemaire",
    "Noel",
    "Meyer",
    "Dufour",
    "Meunier",
    "Brun",
    "Blanchard",
    "Giraud",
    "Joly",
    "Riviere",
    "Lucas",
    "Brunet",
    "Gaillard",
    "Barbier",
    "Arnaud",
    "Martinez",
    "Gerard",
    "Roche",
    "Renard",
    "Schmitt",
    "Roy",
    "Leroux",
    "Colin",
    "Vidal",
    "Caron",
    "Picard",
    "Roger",
    "Fabre",
    "Aubert",
    "Lemoine",
    "Renaud",
    "Dumas",
    "Lacroix",
    "Olivier",
    "Philippe",
]


@dataclass(frozen=True)
class Person:
    """Describe one expected account independently from its database identifier."""

    first_name: str
    last_name: str
    email: str
    role: str
    promotion: str | None = None
    subjects: tuple[str, ...] = ()


def email_part(value: str) -> str:
    """Normalize a synthetic name without retaining accents or punctuation."""
    return "".join(
        character
        for character in unicodedata.normalize("NFKD", value.casefold())
        if character.isascii() and character.isalnum()
    )


def build_people(settings: Settings) -> tuple[list[Person], list[Person]]:
    """Build globally distinct pupils and staff for any supported scenario size."""
    pupils = []
    for cohort in settings.classes():
        for _ in range(settings.pupils_per_class):
            index = len(pupils)
            first = FIRST_NAMES[index % len(FIRST_NAMES)]
            family = LAST_NAMES[(index + index // len(FIRST_NAMES)) % len(LAST_NAMES)]
            if index >= len(FIRST_NAMES) * len(LAST_NAMES):
                raise SeedError("La réserve de noms est insuffisante pour ce scénario.")
            pupils.append(
                Person(
                    first,
                    family,
                    f"{settings.namespace}.student.{index + 1:04d}@{settings.email_domain}",
                    "user",
                    cohort.identifier,
                )
            )
    staff_first = [
        "Aurélien",
        "Blandine",
        "Célestin",
        "Dorothée",
        "Eugène",
        "Faustine",
        "Gaspard",
        "Isaline",
        "Léonard",
        "Mélisande",
        "Nathanaël",
        "Olympia",
        "Philémon",
    ]
    staff_last = [
        "Desforges",
        "Vauclair",
        "Beaulieu",
        "Montclar",
        "Davenne",
        "Valcourt",
        "Sorel",
        "Belcour",
        "Chanterive",
        "Delacour",
        "Desaulnes",
        "Dorléans",
        "Villedieu",
    ]
    staff = []
    names = {
        ("teacher", "si"): (0, 1),
        ("teacher", "maths"): (2, 3),
        ("teacher", "physics"): (4, 5),
        ("teacher", "english"): (6,),
        ("teacher", "french"): (7,),
        ("teacher", "german"): (8,),
        ("kholleur", "si"): (9,),
        ("kholleur", "maths"): (10,),
        ("kholleur", "physics"): (11,),
        ("kholleur", "english"): (12,),
    }
    for role, counts in (
        ("teacher", settings.teacher_counts),
        ("kholleur", settings.kholleur_counts),
    ):
        for subject, count in counts.items():
            for ordinal in range(count):
                choices = names.get((role, subject), ())
                index = choices[ordinal] if ordinal < len(choices) else ordinal % len(staff_first)
                first = staff_first[index % len(staff_first)]
                family = staff_last[index % len(staff_last)]
                if ordinal >= len(choices):
                    family += (
                        email_part(role + subject).capitalize()
                        + FIRST_NAMES[ordinal % len(FIRST_NAMES)]
                    )
                subjects = [subject]
                if role == "teacher":
                    if subject in {"si", "maths"}:
                        subjects.append("computer_science")
                    if subject in {"si", "maths", "physics"}:
                        subjects.append("tipe")
                staff.append(
                    Person(
                        first,
                        family,
                        f"{settings.namespace}.{role}.{subject}.{ordinal + 1}"
                        f"@{settings.email_domain}",
                        role,
                        subjects=tuple(subjects),
                    )
                )
    people = [*pupils, *staff]
    if len({person.email for person in people}) != len(people) or len(
        {(person.first_name, person.last_name) for person in people}
    ) != len(people):
        raise SeedError("Les identités générées doivent être distinctes.")
    return pupils, staff
