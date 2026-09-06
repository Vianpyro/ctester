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
        {"id": "premiere-reussite", "sur": "reussites", "seuil": 1,
         "titre": "Premier exercice réussi",
         "description": "Tu as fait passer tous les tests d'un exercice."},
        {"id": "cinq-reussites", "sur": "reussites", "seuil": 5,
         "titre": "Cinq exercices réussis",
         "description": "Cinq exercices différents, tous tests passés."},
        {"id": "dix-reussites", "sur": "reussites", "seuil": 10,
         "titre": "Dix exercices réussis",
         "description": "Dix exercices différents, tous tests passés."},
        {"id": "premiere-competence", "sur": "competences", "seuil": 1,
         "titre": "Première compétence pratiquée",
         "description": "Tu as pratiqué un exercice qui annonce une compétence."},
        {"id": "trois-competences", "sur": "competences", "seuil": 3,
         "titre": "Trois compétences pratiquées",
         "description": "Ta pratique touche trois compétences différentes."},
        {"id": "premiere-verification", "sur": "verifications", "seuil": 1,
         "titre": "Première vérification réussie",
         "description": "Tu as réussi une activité de vérification, pas seulement "
                        "un exercice de pratique."},
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
            {"id": "verifie", "titre": "Vérifié",
             "description": "Toutes les vérifications ouvertes de cette compétence "
                            "sont réussies. C'est une capacité démontrée, pas une note."},
            {"id": "en-progression", "titre": "En progression",
             "description": "Au moins une vérification réussie ; il en reste à faire."},
            {"id": "a-consolider", "titre": "À consolider",
             "description": "Tu as tenté une vérification sans la réussir. "
                            "Pratique encore, puis réessaie -- rien n'est retiré."},
            {"id": "non-verifie", "titre": "Pas encore vérifié",
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
    """{rang, depuis, prochain, restant} for this balance. `prochain` None at the top.

    The rank is 1-based: nobody is "level 0". `restant` is what is still
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
        "rang": rang,
        "depuis": depuis,
        "prochain": prochain,
        "restant": (prochain - xp) if prochain is not None else 0,
    }


def succes_atteints(faits):
    """The ids of achievements these facts unlock, in declared order.

    `faits` is a dict of counters ({"reussites": 3, ...}). A missing fact is
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
