"""Seed realistic SI practice questions linked to the scenario's competencies."""

from .client import Client
from .configuration import SeedError
from .curricula import SI_TREE

# The statement is formatted as text. Put LaTeX in the question or choices.
SI_QUESTIONS = (
    (
        "Réducteur à engrenages",
        ("B.2", "C.2"),
        (
            "Le motoréducteur d’un convoyeur tourne à 1 500 tr/min en entrée. Le pignon moteur a "
            "20 dents et la roue menée en a 60. On néglige les pertes."
        ),
        r"Calculez la vitesse de sortie en tr/min avec $n_s = n_e\, Z_e/Z_s$.",
        {"kind": "number", "expected": "500"},
    ),
    (
        "Couple sur le tambour",
        ("C.2", "F.3"),
        (
            "Un treuil soulève une charge à vitesse constante. Le câble exerce une force de "
            "180 N perpendiculairement au rayon de 0,08 m du tambour."
        ),
        r"Quel couple le tambour doit-il fournir, en N·m, si $C = F r$ ?",
        {"kind": "number", "expected": "14,4"},
    ),
    (
        "Puissance d’un vérin",
        ("B.1", "C.2"),
        (
            "Sur un banc didactique, un vérin pousse une pièce avec un effort constant de "
            "250 N. La tige avance à 0,12 m/s dans la direction de l’effort."
        ),
        r"Calculez la puissance mécanique en watts à l’aide de $P = Fv$.",
        {"kind": "number", "expected": "30"},
    ),
    (
        "Courant d’un capteur",
        ("C.2",),
        (
            "Un capteur industriel transmet sa mesure par une boucle de courant. Une résistance "
            "de 250 Ω convertit le courant en tension. Le voltmètre affiche 3 V."
        ),
        r"Avec $U = RI$, quel est le courant mesuré, en milliampères ?",
        {"kind": "number", "expected": "12"},
    ),
    (
        "Énergie d’un chariot",
        ("C.1", "C.2"),
        (
            "Un chariot de manutention de 40 kg roule à 1,5 m/s. On cherche à estimer l’énergie "
            "que son frein devra dissiper. Les pièces en rotation sont négligées."
        ),
        r"Calculez l’énergie cinétique en joules avec $E_c = \frac12 mv^2$.",
        {"kind": "number", "expected": "45"},
    ),
    (
        "Période d’échantillonnage",
        ("B.1", "C.3"),
        (
            "La position d’un axe est acquise à 80 Hz pendant un essai. Les acquisitions sont "
            "espacées régulièrement dans le temps."
        ),
        r"En utilisant $T_e = 1/f_e$, donnez la période d’échantillonnage en secondes.",
        {"kind": "number", "expected": "1/80"},
    ),
    (
        "Raideur d’un ressort",
        ("B.2", "D.3"),
        (
            "Lors d’un essai statique, un ressort horizontal s’allonge de 8 mm sous une force de "
            "24 N. L’allongement reste dans le domaine linéaire."
        ),
        r"Déterminez la raideur $k$ en N/m à partir de $F=k\Delta x$.",
        {"kind": "number", "expected": "3000"},
    ),
    (
        "Vitesse en bout de bras",
        ("C.2", "F.3"),
        (
            "Le bras d’un robot tourne autour d’un pivot fixe à la vitesse angulaire de "
            "2,4 rad/s. La pince se situe à 350 mm de l’axe."
        ),
        r"Calculez sa vitesse linéaire en m/s avec $v=\omega r$. Arrondissez au centième.",
        {"kind": "number", "expected": "0,84", "tolerance": "0,005"},
    ),
    (
        "Exigence de positionnement",
        ("A.1",),
        (
            "Une pince robotisée positionne des pièces pour une opération de vissage. "
            "Le responsable souhaite traduire le besoin de précision en un critère vérifiable."
        ),
        "Quelle exigence permet de vérifier directement la précision de positionnement ?",
        {
            "kind": "choice",
            "options": [
                "La pince doit être légère.",
                r"L’écart de position doit être inférieur ou égal à $0{,}2\,\mathrm{mm}$.",
                "La pince utilise un moteur électrique.",
                "La pince doit se déplacer rapidement.",
            ],
            "correct": [1],
        },
    ),
    (
        "Frontière d’un axe motorisé",
        ("A.2", "A.3"),
        (
            "Le système étudié comprend le moteur et la vis, jusqu’à la liaison avec le chariot. "
            "L’alimentation électrique, le chariot et son capteur de position sont extérieurs."
        ),
        "Quels échanges traversent la frontière de l’axe dans le sens indiqué ?",
        {
            "kind": "choice",
            "options": [
                "Énergie électrique reçue de l’alimentation",
                "Transmission du couple du moteur à la vis",
                "Action mécanique de la vis sur le chariot",
                "Signal envoyé par le capteur au poste d’acquisition, tous deux extérieurs",
            ],
            "correct": [0, 2],
        },
    ),
    (
        "Écart sur un temps de réponse",
        ("A.4",),
        (
            "Le cahier des charges fixe un temps de réponse maximal de 0,40 s. Le modèle prédit "
            "0,35 s et un essai réalisé dans les conditions prévues donne 0,52 s."
        ),
        "Quelles conclusions sont justifiées par ces valeurs ?",
        {
            "kind": "choice",
            "options": [
                "Le résultat mesuré respecte le cahier des charges.",
                r"Le résultat mesuré dépasse la limite de $0{,}12\,\mathrm{s}$.",
                r"Le résultat mesuré dépasse la prédiction de $0{,}17\,\mathrm{s}$.",
                "La prédiction suffit à valider le temps de réponse réel.",
            ],
            "correct": [1, 2],
        },
    ),
    (
        "Choix d’un matériau",
        ("A.5", "F.2"),
        (
            "Une pièce mobile doit être légère et facile à usiner. À volume identique, les deux "
            "matériaux envisagés satisfont les exigences mécaniques et sont usinables."
        ),
        (
            r"On compare aluminium ($2{,}7\,\mathrm{g/cm^3}$) et acier ($7{,}8\,\mathrm{g/cm^3}$). "
            "Quel matériau minimise la masse ?"
        ),
        {
            "kind": "choice",
            "options": [
                "L’acier",
                "L’aluminium",
                "Les deux donnent la même masse",
                "Le volume seul suffit à choisir",
            ],
            "correct": [1],
        },
    ),
    (
        "Validation sur des essais indépendants",
        ("B.3",),
        (
            "Les paramètres d’un modèle de frottement ont été identifiés à partir de trois essais. "
            "On souhaite savoir si le modèle prédit correctement le comportement "
            "sur la plage utile."
        ),
        "Quel protocole teste sa capacité de prédiction ?",
        {
            "kind": "choice",
            "options": [
                "Refaire uniquement le calcul sur les trois courbes d’identification",
                "Choisir les courbes qui ressemblent le plus au modèle",
                "Comparer des prédictions à de nouveaux essais sans réajuster les paramètres",
                "Remplacer les valeurs mesurées par celles calculées",
            ],
            "correct": [2],
        },
    ),
    (
        "Essai d’un asservissement",
        ("D.2",),
        (
            "Deux réglages d’un correcteur sont à comparer. "
            "On souhaite isoler l’influence du réglage sur la réponse à un échelon de position."
        ),
        "Quelles précautions rendent les essais comparables ?",
        {
            "kind": "choice",
            "options": [
                "Appliquer la même consigne aux deux essais",
                "Modifier la charge mécanique entre les essais",
                "Conserver le même état initial et la même période d’acquisition",
                "Comparer des durées d’enregistrement différentes sans les indiquer",
            ],
            "correct": [0, 2],
        },
    ),
    (
        "Architecture d’une régulation de vitesse",
        ("F.1",),
        (
            "Le moteur d’un tapis doit maintenir la vitesse demandée lorsque la charge varie. "
            "Le système utilise une régulation par retour de vitesse."
        ),
        "Quels éléments sont nécessaires pour réaliser cette boucle de régulation ?",
        {
            "kind": "choice",
            "options": [
                "Une mesure de la vitesse réelle",
                "Un comparateur entre consigne et vitesse mesurée",
                "Un correcteur agissant sur la commande du moteur",
                "Un afficheur du nombre total de pièces transportées",
            ],
            "correct": [0, 1, 2],
        },
    ),
    (
        "Compte rendu d’un essai",
        ("E.1", "E.2"),
        (
            "Un rapport d’essai contient une courbe de vitesse en fonction du temps. Le lecteur "
            "doit pouvoir interpréter les valeurs et identifier le réglage testé."
        ),
        "Quelles informations faut-il faire apparaître sur la figure ou dans sa légende ?",
        {
            "kind": "choice",
            "options": [
                "Les grandeurs et unités des deux axes",
                "Le réglage utilisé pendant l’essai",
                "Un titre décoratif sans indication de la grandeur mesurée",
                "Les conditions d’essai utiles à l’interprétation",
            ],
            "correct": [0, 1, 3],
        },
    ),
    (
        "Mesure de vitesse de rotation",
        ("B.1", "D.1"),
        (
            "Un dispositif portatif doit mesurer directement la vitesse d’un arbre tournant. "
            "Il affiche le résultat en tours par minute sans mesure de couple."
        ),
        "Quel est le nom générique de cet instrument ?",
        {"kind": "text", "accepted": ["tachymètre", "un tachymètre"]},
    ),
    (
        "Unité du courant",
        ("B.1", "E.2"),
        (
            "Dans le compte rendu d’un essai moteur, la colonne de courant est repérée par le "
            "symbole A. On veut écrire le nom complet de cette unité."
        ),
        r"Quelle est l’unité SI de la grandeur $I$ ? Donnez son nom.",
        {"kind": "text", "accepted": ["ampère"]},
    ),
    (
        "Liaison d’un axe de rotation",
        ("A.3", "B.2"),
        (
            "Un arbre est guidé par deux roulements et retenu axialement. Le modèle idéal autorise "
            "seulement une rotation autour de l’axe, sans déplacement axial."
        ),
        "Comment se nomme la liaison mécanique idéalisée entre l’arbre et le bâti ?",
        {"kind": "text", "accepted": ["pivot", "liaison pivot"]},
    ),
    (
        "Premier prototype d’un carter",
        ("G.1", "G.2"),
        (
            "Pour vérifier l’encombrement d’un carter, l’équipe fabrique une seule maquette en "
            "polymère. Une buse dépose du filament fondu couche par couche selon un modèle 3D."
        ),
        "Nommez le procédé de fabrication utilisé.",
        {
            "kind": "text",
            "accepted": [
                "impression 3D",
                "fabrication additive",
                "dépôt de filament fondu",
                "FDM",
                "FFF",
            ],
        },
    ),
)


def seed_si_quiz(client: Client, namespace: str, subject_id: int, graph: dict) -> None:
    """Create missing SI sheets and resolve required competencies before sending any writes."""
    path = f"/quiz/subjects/{subject_id}"
    existing = {row["title"] for row in client.request("GET", path)["questions"]}
    names = {
        f"{root}.{index}": name
        for root, (_, children) in zip("ABCDEFG", SI_TREE, strict=True)
        for index, name in enumerate(children, 1)
    }
    ids_by_name: dict[str, list[int]] = {}
    for node in graph["nodes"]:
        ids_by_name.setdefault(node["name"], []).append(node["id"])
    pending = []
    for title, codes, statement, prompt, rule in SI_QUESTIONS:
        title = f"{title} · {namespace}"
        if title in existing:
            continue
        competency_ids = []
        for code in codes:
            ids = ids_by_name.get(names[code], [])
            if len(ids) != 1:
                raise SeedError(
                    f"Compétence SI {code} introuvable ou ambiguë : « {names[code]} »."
                )
            competency_ids.append(ids[0])
        pending.append(
            {
                "title": title,
                "statement": statement,
                "prompt": prompt,
                "rule": rule,
                "competency_ids": competency_ids,
            }
        )
    for question in pending:
        client.request("POST", path + "/questions", question)
    print(
        f"Fiches Quiz SI : {len(pending)} créées, {len(SI_QUESTIONS) - len(pending)} conservées."
    )
