# Every balancing number lives here. Achievement, card and frame ids are stored
# in the database: renaming one orphans what students already earned.
POLICY = {
    "version": "pilote-1",

    "xp": {
        "intro": 10,
        "foundation": 15,
        "intermediate": 20,
        "advanced": 30,
        "default": 10,
    },

    "daily_cap": 100,

    "levels": [0, 30, 80, 150, 250, 400, 600],

    "achievements": [
        {"id": "premiere-reussite", "on": "solved", "threshold": 1,
         "title": "Premier exercice réussi",
         "description": "Tu as fait passer tous les tests d'un exercice."},
        {"id": "cinq-reussites", "on": "solved", "threshold": 5,
         "title": "Cinq exercices réussis",
         "description": "Cinq exercices différents, tous tests passés."},
        {"id": "dix-reussites", "on": "solved", "threshold": 10,
         "title": "Dix exercices réussis",
         "description": "Dix exercices différents, tous tests passés."},
        {"id": "premiere-competence", "on": "skills", "threshold": 1,
         "title": "Première compétence pratiquée",
         "description": "Tu as pratiqué un exercice qui annonce une compétence."},
        {"id": "trois-competences", "on": "skills", "threshold": 3,
         "title": "Trois compétences pratiquées",
         "description": "Ta pratique touche trois compétences différentes."},
        {"id": "premiere-verification", "on": "verifications", "threshold": 1,
         "title": "Première vérification réussie",
         "description": "Tu as réussi une activité de vérification, pas seulement "
                        "un exercice de pratique."},
    ],

    "cards": [
        {"id": "E-01", "name": "Résistance", "family": "electrical",
         "exercises": ["tp2-ex3"],
         "condition": "Réussir la loi d'Ohm (TP2)"},
        {"id": "M-04", "name": "Roulement", "family": "mechanical",
         "exercises": ["tp2-ex0", "tp2-ex1", "tp2-ex2", "tp2-ex3", "tp2-ex4"],
         "condition": "Réussir tout le TP2"},
        {"id": "E-07", "name": "Relais", "family": "electrical",
         "exercises": ["verif-tp1"],
         "condition": "Réussir la vérification du TP1"},
        {"id": "M-02", "name": "Engrenage", "family": "mechanical",
         "exercises": ["tp1-ex1"],
         "condition": "Réussir le premier exercice du TP1"},
        {"id": "P-03", "name": "Vérin", "family": "production",
         "exercises": ["tp3-ex1", "tp3-ex2", "tp3-ex3"],
         "condition": "Réussir trois exercices du TP3"},
        {"id": "E-12", "name": "Diode", "family": "electrical",
         "exercises": ["verif-tp2"],
         "condition": "Réussir la vérification du TP2"},
        {"id": "M-09", "name": "Ressort", "family": "mechanical",
         "exercises": ["tp2-ex5", "tp2-ex6"],
         "condition": "Réussir les deux derniers exercices du TP2"},
        {"id": "P-06", "name": "Capteur", "family": "production",
         "exercises": ["verif-tp2-debogage"],
         "condition": "Réussir la vérification de débogage du TP2"},
    ],

    "leaderboard": {
        "minimum_cohort": 5,
        "visible_rows": 5,
        "divisions": [
            {"id": "atelier", "title": "Atelier", "threshold": 0},
            {"id": "machiniste", "title": "Machiniste", "threshold": 8},
            {"id": "ingenierie", "title": "Ingénierie", "threshold": 20},
        ],
    },

    "aliases": {
        "parts": [
            "Rotor",
            "Palier",
            "Came",
            "Vilebrequin",
            "Ressort",
            "Engrenage",
            "Roulement",
            "Vérin",
            "Relais",
            "Capteur",
            "Arbre",
            "Piston",
            "Moteur",
            "Module",
            "Circuit",
            "Processeur",
            "Algorithme",
            "Compilateur",
            "Pointeur",
            "Registre",
            "Octet",
            "Paquet",
            "Serveur",
            "Noyau",
            "Thread",
            "Signal",
            "Bit",
            "Vecteur",
            "Graphe",
            "Nœud"
        ],
        "adjectives": [
            "cuivré",
            "lisse",
            "excentré",
            "primaire",
            "trempé",
            "rodé",
            "hélicoïdal",
            "conique",
            "pneumatique",
            "bistable",
            "inductif",
            "cranté",
            "cannelé",
            "flottant",
            "modulaire",
            "numérique",
            "logique",
            "robuste",
            "compact",
            "optimisé"
        ]
    },

    "frames": [
        {"id": "simple", "title": "Trait simple", "threshold": 1},
        {"id": "coupe", "title": "Trait de coupe", "threshold": 3},
        {"id": "tolerance", "title": "Cote de tolérance", "threshold": 6},
    ],

    "mastery": {
        "bands": [
            {"id": "verifie", "title": "Vérifié",
             "description": "Toutes les vérifications ouvertes de cette compétence "
                            "sont réussies. C'est une capacité démontrée, pas une note."},
            {"id": "en-progression", "title": "En progression",
             "description": "Au moins une vérification réussie ; il en reste à faire."},
            {"id": "a-consolider", "title": "À consolider",
             "description": "Tu as tenté une vérification sans la réussir. "
                            "Pratique encore, puis réessaie -- rien n'est retiré."},
            {"id": "non-verifie", "title": "Pas encore vérifié",
             "description": "Aucune vérification tentée pour cette compétence."},
        ],
    },
}

VERSION = POLICY["version"]

ACHIEVEMENTS = {s["id"]: s for s in POLICY["achievements"]}

BANDS = {b["id"]: b for b in POLICY["mastery"]["bands"]}


def xp_for_solve(entry):
    table = POLICY["xp"]
    return int(table.get((entry or {}).get("difficulty"), table["default"]))


def daily_cap():
    return int(POLICY["daily_cap"])


def level(xp):
    thresholds = POLICY["levels"]
    xp = max(int(xp or 0), 0)
    rank = 1
    for n, threshold in enumerate(thresholds, 1):
        if xp >= threshold:
            rank = n
    since = thresholds[rank - 1]
    upcoming = thresholds[rank] if rank < len(thresholds) else None
    return {
        "rank": rank,
        "since": since,
        "next": upcoming,
        "remaining": (upcoming - xp) if upcoming is not None else 0,
    }


def achievements_reached(facts):
    return [s["id"] for s in POLICY["achievements"]
            if int((facts or {}).get(s["on"], 0)) >= s["threshold"]]


def mastery_band(solved, attempted, total):
    solved, attempted, total = int(solved), int(attempted), int(total)
    if attempted <= 0 or total <= 0:
        return "non-verifie"
    if solved >= total:
        return "verifie"
    if solved >= 1:
        return "en-progression"
    return "a-consolider"


CARD_PREFIX = "card:"

CARDS = {CARD_PREFIX + c["id"]: c for c in POLICY["cards"]}


def cards_earned(solved):
    solved = set(solved or ())
    return [CARD_PREFIX + c["id"] for c in POLICY["cards"]
            if c["exercises"] and solved.issuperset(c["exercises"])]


def minimum_cohort():
    return int(POLICY["leaderboard"]["minimum_cohort"])


def visible_rows():
    return int(POLICY["leaderboard"]["visible_rows"])


def division(total):
    divisions = POLICY["leaderboard"]["divisions"]
    reached = divisions[0]
    for entry in divisions:
        if int(total or 0) >= entry["threshold"]:
            reached = entry
    return dict(reached)


def divisions():
    return [dict(d) for d in POLICY["leaderboard"]["divisions"]]


def possible_aliases():
    vocabulary = POLICY["aliases"]
    return [part + " " + adjective
            for part in vocabulary["parts"]
            for adjective in vocabulary["adjectives"]]


FRAMES = {c["id"]: c for c in POLICY["frames"]}


def unlocked_frames(rank):
    return [dict(c) for c in POLICY["frames"] if int(rank or 1) >= c["threshold"]]
