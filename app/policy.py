# Every balancing number lives here. Achievement, card and frame ids are stored
# in the database: renaming one orphans what students already earned. Their wording
# is the page's, under achievement.<id>, division.<id>, frame.<id> and band.<id>.
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

    # Grouped by fact, each ladder in rising order: the page shows them in this order.
    "achievements": [
        {"id": "premier-test", "on": "practiced", "threshold": 1},
        {"id": "vingt-exercices-pratiques", "on": "practiced", "threshold": 20},
        {"id": "cinquante-exercices-pratiques", "on": "practiced", "threshold": 50},
        {"id": "premiere-reussite", "on": "solved", "threshold": 1},
        {"id": "cinq-reussites", "on": "solved", "threshold": 5},
        {"id": "dix-reussites", "on": "solved", "threshold": 10},
        {"id": "vingt-cinq-reussites", "on": "solved", "threshold": 25},
        {"id": "cinquante-reussites", "on": "solved", "threshold": 50},
        {"id": "soixante-quinze-reussites", "on": "solved", "threshold": 75},
        {"id": "cent-reussites", "on": "solved", "threshold": 100},
        {"id": "tout-resolu", "on": "complete", "threshold": 1},
        {"id": "premier-lab-complet", "on": "labs", "threshold": 1},
        {"id": "cinq-labs-complets", "on": "labs", "threshold": 5},
        {"id": "dix-labs-complets", "on": "labs", "threshold": 10},
        {"id": "premier-programme", "on": "solved_io", "threshold": 1},
        {"id": "dix-programmes", "on": "solved_io", "threshold": 10},
        {"id": "vingt-cinq-programmes", "on": "solved_io", "threshold": 25},
        {"id": "premiere-fonction", "on": "solved_unity", "threshold": 1},
        {"id": "dix-fonctions", "on": "solved_unity", "threshold": 10},
        {"id": "vingt-cinq-fonctions", "on": "solved_unity", "threshold": 25},
        {"id": "premier-quiz", "on": "solved_quiz", "threshold": 1},
        {"id": "cinq-quiz", "on": "solved_quiz", "threshold": 5},
        {"id": "dix-quiz", "on": "solved_quiz", "threshold": 10},
        {"id": "premier-intermediaire", "on": "solved_intermediate", "threshold": 1},
        {"id": "dix-intermediaires", "on": "solved_intermediate", "threshold": 10},
        {"id": "vingt-cinq-intermediaires", "on": "solved_intermediate", "threshold": 25},
        {"id": "premier-avance", "on": "solved_advanced", "threshold": 1},
        {"id": "cinq-avances", "on": "solved_advanced", "threshold": 5},
        {"id": "dix-avances", "on": "solved_advanced", "threshold": 10},
        {"id": "premier-bonus", "on": "solved_bonus", "threshold": 1},
        {"id": "cinq-bonus", "on": "solved_bonus", "threshold": 5},
        {"id": "premiere-competence", "on": "skills", "threshold": 1},
        {"id": "trois-competences", "on": "skills", "threshold": 3},
        {"id": "six-competences", "on": "skills", "threshold": 6},
        {"id": "douze-competences", "on": "skills", "threshold": 12},
        {"id": "vingt-competences", "on": "skills", "threshold": 20},
        {"id": "premiere-verification", "on": "verifications", "threshold": 1},
        {"id": "trois-verifications", "on": "verifications", "threshold": 3},
        {"id": "cinq-verifications", "on": "verifications", "threshold": 5},
        {"id": "dix-verifications", "on": "verifications", "threshold": 10},
        {"id": "premiere-competence-verifiee", "on": "skills_verified", "threshold": 1},
        {"id": "trois-competences-verifiees", "on": "skills_verified", "threshold": 3},
        {"id": "cinq-competences-verifiees", "on": "skills_verified", "threshold": 5},
        {"id": "remontee", "on": "comebacks", "threshold": 1},
        {"id": "trois-remontees", "on": "comebacks", "threshold": 3},
        {"id": "perseverance", "on": "persevered", "threshold": 1},
        {"id": "cinq-perseverances", "on": "persevered", "threshold": 5},
        {"id": "quinze-perseverances", "on": "persevered", "threshold": 15},
        {"id": "dix-tests", "on": "tests", "threshold": 10},
        {"id": "cent-tests", "on": "tests", "threshold": 100},
        {"id": "cinq-cents-tests", "on": "tests", "threshold": 500},
        {"id": "trois-jours", "on": "days", "threshold": 3},
        {"id": "dix-jours", "on": "days", "threshold": 10},
        {"id": "vingt-cinq-jours", "on": "days", "threshold": 25},
        {"id": "cinquante-jours", "on": "days", "threshold": 50},
        {"id": "premiere-carte", "on": "cards", "threshold": 1},
        {"id": "cinq-cartes", "on": "cards", "threshold": 5},
        {"id": "dix-cartes", "on": "cards", "threshold": 10},
    ],

    "leaderboard": {
        "minimum_cohort": 5,
        "visible_rows": 5,
        "divisions": [
            {"id": "atelier", "threshold": 0},
            {"id": "machiniste", "threshold": 8},
            {"id": "ingenierie", "threshold": 20},
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
        {"id": "simple", "threshold": 1},
        {"id": "coupe", "threshold": 3},
        {"id": "tolerance", "threshold": 6},
    ],

    "mastery": {
        "bands": [
            {"id": "verifie"},
            {"id": "en-progression"},
            {"id": "a-consolider"},
            {"id": "non-verifie"},
        ],
    },
}

VERSION = POLICY["version"]

ACHIEVEMENTS = {s["id"]: s for s in POLICY["achievements"]}

BANDS = {b["id"]: b for b in POLICY["mastery"]["bands"]}


def xp_for_solve(entry):
    table = POLICY["xp"]
    return int(table.get(entry.get("difficulty"), table["default"]))


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


# Cards name exercises, so they come from the content's cards.json, not from here.
def cards_by_key(cards):
    return {CARD_PREFIX + c["id"]: c for c in cards or ()
            if isinstance(c, dict) and isinstance(c.get("id"), str)}


def cards_earned(solved, cards):
    solved = set(solved or ())
    return [CARD_PREFIX + c["id"] for c in cards or ()
            if c.get("exercises") and solved.issuperset(c["exercises"])]


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
    return [dict(c) for c in POLICY["frames"] if int(rank) >= c["threshold"]]
