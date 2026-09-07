#!/usr/bin/env python3
"""ctester -- the gamification policy: NUMBERS, not logic.

EVERYTHING TUNABLE LIVES IN `POLICY`, at the top, and nothing else in this
repo holds an XP amount, a level threshold, an achievement label, or a
mastery band label.
That is this file's whole purpose: tuning the first term means editing these
numbers, and it must never require rereading the API to do it. The functions
below only READ this table.

THESE VALUES ARE PROVISIONAL. They have not been observed on a cohort; they
are deliberately conservative, and `version` dates them. A transaction and an
achievement, once recorded, carry the version that produced them: changing an
amount therefore never rewrites history, it opens a new page.

WHAT XP IS NOT: a grade, a skill, verified mastery. It is a practice-activity
counter, and the interface says so on screen. The only fact that produces it
is a FIRST complete solve of a published exercise, observed by the server
reading the worker's verdict -- never a failure, never a repeat, never a
declaration from the browser.
"""

POLICY = {
    "version": "pilote-1",

    # What a first complete solve of an exercise is worth, based on the
    # difficulty the public catalog advertises (`difficulty`). An exercise
    # with no declared difficulty takes `defaut`: granting nothing would
    # punish the student for metadata missing on the instructor's side.
    "xp": {
        "intro": 10,
        "foundation": 15,
        "intermediate": 20,
        "advanced": 30,
        "defaut": 10,
    },

    # DAILY CAP, defense in depth only. The "once per exercise" rule already
    # makes farming impossible; this cap exists so a suddenly more generous
    # catalog, or a bulk import, does not manufacture an absurd balance in one
    # evening. It NEVER blocks practice: past it, the exercise still gets
    # graded normally, it simply earns nothing more that day.
    "plafond_quotidien": 100,

    # Cumulative XP required for each level, from level 1 to the last. No
    # titles: "expert" on an activity counter would suggest a qualification,
    # which this number is not.
    "niveaux": [0, 30, 80, 150, 250, 400, 600],

    # FEW, PRIVATE, NOT MANDATORY, and derived from facts the server observes
    # itself. No "zero errors": debugging is the work, not a failure. `sur`
    # names the fact counted, `seuil` the value to reach -- one more
    # definition is one more line, not code.
    "succes": [
        {"id": "premiere-reussite", "sur": "solved", "seuil": 1,
         "title": "Premier exercice réussi",
         "description": "Tu as fait passer tous les tests d'un exercice."},
        {"id": "cinq-reussites", "sur": "solved", "seuil": 5,
         "title": "Cinq exercices réussis",
         "description": "Cinq exercices différents, tous tests passés."},
        {"id": "dix-reussites", "sur": "solved", "seuil": 10,
         "title": "Dix exercices réussis",
         "description": "Dix exercices différents, tous tests passés."},
        {"id": "premiere-competence", "sur": "skills", "seuil": 1,
         "title": "Première compétence pratiquée",
         "description": "Tu as pratiqué un exercice qui annonce une compétence."},
        {"id": "trois-competences", "sur": "skills", "seuil": 3,
         "title": "Trois compétences pratiquées",
         "description": "Ta pratique touche trois compétences différentes."},
        {"id": "premiere-verification", "sur": "verifications", "seuil": 1,
         "title": "Première vérification réussie",
         "description": "Tu as réussi une activité de vérification, pas seulement "
                        "un exercice de pratique."},
    ],

    # THE COLLECTION (design 1e): ONE CARD PER EXERCISE FAMILY, and the
    # criterion is a list of exercises to have SOLVED. Nothing is drawn, nothing
    # is bought, nothing expires, and a card grants no advantage -- it is a
    # trace of what was done, which is the only kind of collectible that
    # survives student-motivations.md's "no pay-to-win, no fear of missing out".
    #
    # THE SAME MECHANISM AS AN ACHIEVEMENT, ON PURPOSE: cards land in
    # `achievement_unlocked` under their own id, so there is no new table, no
    # new GRANT, nothing more to erase in `forget()`, and the primary key is
    # again what makes "once only" true. `card:` prefixes the id so a card and
    # an achievement can never collide, and so a card never shows up in the
    # achievements list.
    #
    # `exercises` LISTS PUBLISHED IDS. A card whose exercises are not all open
    # is simply unreachable, and displays as locked with its condition -- a
    # condition one can read is the difference between a collection and a
    # slot machine.
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

    # THE LEADERBOARD (design 1c). OPT-IN, WEEKLY, AND COUNTED ON FIRST
    # SOLVES ONLY -- which is already phase 1's idempotence key
    # (`solved:<exercise>`), so redoing a lab earns nothing here either and the
    # daily cap has no business applying.
    #
    # `minimum_cohort` IS A PRIVACY CONTROL, not a display nicety: under it,
    # a ranking of three people names everyone including the last, and
    # privacy.md forbids exactly that. Below the threshold, only one's own line
    # comes back.
    #
    # `visible_rows` IS WHY NOBODY IS NAMED LAST. Only the top of the table is
    # listed; everyone else sees their own row and the step to the one above.
    "leaderboard": {
        "minimum_cohort": 5,
        "visible_rows": 5,
        # The divisions, low to high, by first solves accumulated over the
        # term. THEY ONLY GO UP: a bad month takes nothing away (ranked.md),
        # so the service reads the best ever reached, never the current week.
        "divisions": [
            {"id": "atelier", "title": "Atelier", "threshold": 0},
            {"id": "machiniste", "title": "Machiniste", "threshold": 8},
            {"id": "ingenierie", "title": "Ingénierie", "threshold": 20},
        ],
    },

    # THE DRAWN ALIAS: a closed vocabulary, so nothing typed by a student can
    # ever land in it. Two lists, one adjective and one part -- 18 x 18 = 324
    # combinations for a cohort of about thirty, which is enough for
    # `draw_alias()` to find a free one in a handful of tries.
    "aliases": {
        "parts": ["Rotor", "Palier", "Came", "Bobine", "Vilebrequin", "Ressort",
                  "Engrenage", "Roulement", "Vérin", "Relais", "Diode",
                  "Capteur", "Poulie", "Arbre", "Piston", "Soupape",
                  "Culasse", "Cardan"],
        "adjectives": ["cuivré", "lisse", "excentrée", "primaire", "trempé",
                       "rodé", "hélicoïdal", "conique", "pneumatique",
                       "bistable", "zener", "inductif", "crantée", "cannelé",
                       "flottant", "tarée", "culottée", "homocinétique"],
    },

    # PLATE FRAMES: decoration, and nothing else. `threshold` is the level
    # from which one is offered; the first is always available so an account
    # that never levels still has a frame.
    "frames": [
        {"id": "simple", "title": "Trait simple", "threshold": 1},
        {"id": "coupe", "title": "Trait de coupe", "threshold": 3},
        {"id": "tolerance", "title": "Cote de tolérance", "threshold": 6},
    ],

    # VERIFIED MASTERY: LABELS, AND NO THRESHOLD.
    #
    # A skill's band is read by COVERAGE -- how many of its open verifications
    # are passed, out of how many exist -- and not by a score. There is
    # therefore nothing to calibrate here: adding a verification to the
    # content makes "verified" more demanding all on its own, with no number
    # moving. This is deliberate: docs/gamification/mastery.md says
    # thresholds, recency weighting and decay are to be validated on data we
    # do not have.
    #
    # ponytail: bands by coverage, no threshold, no recency. The day a cohort
    # has been observed, an "evidence threshold" and a recency weight go HERE,
    # and `bande_maitrise()` is the only function to reread.
    "maitrise": {
        "bandes": [
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

# What the API returns with an unlocked achievement: the definition is here,
# the date and version in the database. A stored id whose definition has
# disappeared is not an error -- it simply no longer displays.
SUCCES = {s["id"]: s for s in POLICY["succes"]}

# Same for mastery bands: the definition is here, the fact in the database.
BANDES = {b["id"]: b for b in POLICY["maitrise"]["bandes"]}


def xp_reussite(entree):
    """The XP of a first solve, based on the catalog's public difficulty."""
    table = POLICY["xp"]
    return int(table.get((entree or {}).get("difficulty"), table["defaut"]))


def plafond_quotidien():
    return int(POLICY["plafond_quotidien"])


def niveau(xp):
    """{rank, since, next, remaining} for this balance. `next` None at the top.

    The rank is 1-based: nobody is "level 0". `remaining` is what is still
    needed, never a percentage -- the interface needs both numbers to write a
    sentence, and a bar with no sentence does not read aloud.
    """
    seuils = POLICY["niveaux"]
    xp = max(int(xp or 0), 0)
    rang = 1
    for n, seuil in enumerate(seuils, 1):
        if xp >= seuil:
            rang = n
    depuis = seuils[rang - 1]
    prochain = seuils[rang] if rang < len(seuils) else None
    return {
        "rank": rang,
        "since": depuis,
        "next": prochain,
        "remaining": (prochain - xp) if prochain is not None else 0,
    }


def succes_atteints(faits):
    """The ids of achievements these facts unlock, in declared order.

    `faits` is a dict of counters ({"solved": 3, ...}). A missing fact is
    zero: adding a criterion to the policy therefore cannot raise for an
    older caller.
    """
    return [s["id"] for s in POLICY["succes"]
            if int((faits or {}).get(s["sur"], 0)) >= s["seuil"]]


def bande_maitrise(reussies, tentees, total):
    """A skill's band, based on the COVERAGE of its verifications.

    `total` is the number of OPEN verifications carrying this skill,
    `tentees` those the student has a verdict for, `reussies` those whose
    latest attempt passed. No threshold: "verified" means "all", which
    hardens on its own as the content grows.

    A low band takes nothing away -- no XP, no achievement, no grade. It
    recommends practicing, and that is all it is allowed to do.
    """
    reussies, tentees, total = int(reussies), int(tentees), int(total)
    if tentees <= 0 or total <= 0:
        return "non-verifie"
    if reussies >= total:
        return "verifie"
    if reussies >= 1:
        return "en-progression"
    return "a-consolider"


# --- The collection (design 1e) ----------------------------------------------
# A card is an achievement wearing another coat: same table, same primary key,
# same "once only". The prefix is what keeps the two apart in one namespace.

CARD_PREFIX = "card:"

CARDS = {CARD_PREFIX + c["id"]: c for c in POLICY["cards"]}


def cards_earned(solved):
    """The ids of cards these solved exercises unlock, in declared order.

    ALL of a card's exercises must be solved: a partial family unlocks
    nothing, and the card says which ones are missing rather than hiding the
    rule. `solved` is a set of PUBLISHED exercise ids -- a card whose
    exercises are not open is simply unreachable, never granted by default.
    """
    solved = set(solved or ())
    return [CARD_PREFIX + c["id"] for c in POLICY["cards"]
            if c["exercises"] and solved.issuperset(c["exercises"])]


# --- The leaderboard (design 1c) ---------------------------------------------


def minimum_cohort():
    return int(POLICY["leaderboard"]["minimum_cohort"])


def visible_rows():
    return int(POLICY["leaderboard"]["visible_rows"])


def division(total):
    """The division for this many first solves, ever. Never below the first.

    DIVISIONS ONLY GO UP, so the caller passes a lifetime count, never a
    weekly one: a quiet week must not demote anybody (ranked.md).
    """
    divisions = POLICY["leaderboard"]["divisions"]
    reached = divisions[0]
    for entry in divisions:
        if int(total or 0) >= entry["threshold"]:
            reached = entry
    return dict(reached)


def divisions():
    return [dict(d) for d in POLICY["leaderboard"]["divisions"]]


def possible_aliases():
    """Every drawable alias, in a stable order. The caller picks, not this."""
    vocabulary = POLICY["aliases"]
    return [part + " " + adjective
            for part in vocabulary["parts"]
            for adjective in vocabulary["adjectives"]]


# --- Plate frames -------------------------------------------------------------


FRAMES = {c["id"]: c for c in POLICY["frames"]}


def unlocked_frames(rank):
    """The frames unlocked at this level. Always at least one."""
    return [dict(c) for c in POLICY["frames"] if int(rank or 1) >= c["threshold"]]
