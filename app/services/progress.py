"""Progression: XP, level, practiced skills, recommendation.

NOTHING IS CACHED IN THE DATABASE. Everything is recomputed on every read from
three append-only fact tables and the public catalog. There is therefore no
projection to rebuild, and changing the policy requires no migration.

WHAT PRODUCES VALUE IS THE SERVER READING THE VERDICT, never the browser. One
rule only: the FIRST complete solve of a published exercise. A failure grants
nothing, redoing the same exercise grants nothing either -- both hold thanks
to the same thing, the event id `solved:<exercise>` whose primary key
refuses the duplicate.

PHASE 2 -- VERIFIED MASTERY. An exercise marked `verification` in the catalog
belongs to a different domain: it grants NO XP and does not count toward any
practice counter. Its verdict writes a piece of evidence into the same
append-only journal (`progress_event`, type `VerificationEvaluated`), and
per-skill bands are DERIVED from it on every read -- there is no mastery
table, any more than there is a balance table.
"""

import state
import policy
from services.catalog import exercices_ouverts


# THE NUMBERS ARE IN policy.py. No balancing value has the right to appear in
# this file: tuning the term must stay an edit of the policy, not a reread of
# the API.

MAX_SKILLS = 40

# The event type of a piece of mastery evidence. `progress_event` already
# carries `ExerciceReussi`: the journal accepts one more type with no
# migration.
VERIFICATION = "VerificationEvaluated"


def exercices_pratique(entries):
    """The open catalog MINUS verifications. The only filter, defined here.

    A verification is not practice (invariant 4): counting it toward
    "exercises practiced", practiced skills or the recommendation would mix
    the two domains across all three screens at once. One filter, one place,
    and every counter goes through it.
    """
    return [entry for entry in entries if not entry.get("verification")]


def verifications(entries):
    """The catalog's OPEN verifications, in course order."""
    return [entry for entry in entries if entry.get("verification")]


def exercise_facts(states, practice):
    """(touched, solved): two sets of exercise ids.

    Both sources are merged. `practice_attempt` knows a job was graded,
    `exercise_state` knows where the exercise stands; an account that
    predates practice attempts only has the second and must still count.
    """
    touched, solved = set(), set()
    for row in states or ():
        exercise = row.get("exercise_id")
        if not exercise:
            continue
        touched.add(exercise)
        if row.get("status") == "solved":
            solved.add(exercise)
    for row in practice or ():
        exercise = row.get("exercise_id")
        if exercise:
            touched.add(exercise)
    return touched, solved


def skills_view(entries, touched, solved):
    """[{id, total, practiced, solved}] in course order.

    "PRACTICED", NEVER "MASTERED". This counter says an exercise carrying
    this skill was submitted and graded, nothing more: the judge is
    self-service. Mastery is the other axis, derived from verifications alone
    (`maitrise_view`), and the two NEVER merge into a single number. The gap
    between them is docs/gamification/mastery.md's entire subject, and the
    day it is forgotten in a label, a grade has been promised.

    `entries` is already filtered by `exercices_pratique` at the caller: a
    verification adds nothing to a practice denominator.
    """
    order, table = [], {}
    for entry in entries:
        for skill in entry.get("skills") or ():
            row = table.get(skill)
            if row is None:
                row = table[skill] = {"id": skill, "total": 0,
                                      "practiced": 0, "solved": 0}
                order.append(row)
            row["total"] += 1
            row["practiced"] += int(entry["id"] in touched)
            row["solved"] += int(entry["id"] in solved)
    return order[:MAX_SKILLS]


def practised_skills(entries, touched):
    """The skills a touched exercise exercised."""
    skills = set()
    for entry in entries:
        if entry["id"] in touched:
            skills.update(entry.get("skills") or ())
    return skills


def recommander(entries, touched, solved):
    """The next exercise to open, or None. DETERMINISTIC: course order.

    First a published, unsolved exercise that revisits an already-practiced
    skill -- consolidating comes before discovering; else the first unsolved
    one; else nothing, and the page says so rather than inventing one.
    """
    known = practised_skills(entries, touched)
    remaining = [e for e in entries if e["id"] not in solved]
    for entry in remaining:
        for skill in entry.get("skills") or ():
            if skill in known:
                return {"exercise_id": entry["id"], "skill": skill}
    if remaining:
        return {"exercise_id": remaining[0]["id"], "skill": None}
    return None


# --- Verified mastery (phase 2) ---------------------------------------------
# Practice is weak evidence, a verification strong evidence. What is stored is
# the ATTEMPT; the band is derived on read, so tightening the rule tomorrow
# also applies to evidence already in the database.


def dernieres_tentatives(evidences):
    """{exercise_id: solved} -- the LATEST attempt of each verification.

    `evidences` arrives newest to oldest: the first one seen per exercise
    wins. Earlier ones stay in the database -- retries stay historical, they
    simply no longer weigh on the displayed band.
    """
    dernier = {}
    for row in evidences or ():
        exercise = (row or {}).get("exercise_id")
        if exercise and exercise not in dernier:
            dernier[exercise] = bool((row.get("payload") or {}).get("passed"))
    return dernier


def verifications_reussies(evidences):
    """Verifications solved AT LEAST ONCE, retries included.

    Deliberately distinct from `dernieres_tentatives`: an achievement is never
    withdrawn, so what it counts must be monotonic. A failed retry pulls a
    band back down -- it must not undo an achievement already earned.
    """
    return {(row or {})["exercise_id"] for row in evidences or ()
            if (row or {}).get("exercise_id")
            and ((row or {}).get("payload") or {}).get("passed")}


def maitrise_view(entries, evidences):
    """[{id, band, passed, attempted, total}] per VERIFIABLE skill.

    A skill only appears if an open verification carries it: saying "not yet
    verified" about a skill no activity verifies would blame the student for
    a content gap.

    `total` counts the skill's open verifications, not attempts: that is what
    makes "verified" harden on its own as content grows, with no threshold
    living anywhere.
    """
    dernier = dernieres_tentatives(evidences)
    order, table = [], {}
    for entry in verifications(entries):
        tentative = dernier.get(entry["id"])
        for skill in entry.get("skills") or ():
            row = table.get(skill)
            if row is None:
                row = table[skill] = {"id": skill, "total": 0,
                                      "attempted": 0, "passed": 0}
                order.append(row)
            row["total"] += 1
            row["attempted"] += int(tentative is not None)
            row["passed"] += int(tentative is True)
    for row in order:
        row["band"] = policy.bande_maitrise(row["passed"], row["attempted"],
                                             row["total"])
    return order[:MAX_SKILLS]


def progression_facts(user):
    """The counters achievements depend on. None if the database does not answer.

    Bounded to the published catalog: a withdrawn exercise must no longer
    unlock anything.
    """
    states = state.read_states(user)
    practice = state.read_practice_summary(user)
    evidences = state.read_events(user, VERIFICATION)
    if states is None or practice is None or evidences is None:
        return None
    entries = exercices_ouverts()
    pratique = exercices_pratique(entries)
    touched, solved = exercise_facts(states, practice)
    published = {e["id"] for e in pratique}
    verifiables = {e["id"] for e in verifications(entries)}
    return {"solved": len(solved & published),
            "skills": len(practised_skills(pratique, touched)),
            "verifications": len(verifications_reussies(evidences) & verifiables)}


def recompenser(user, entry, job_id):
    """A FIRST complete solve -> at most one XP grant.

    Called by the server when it reads a complete verdict, never by the
    browser. Three rules hold at once here:

    - a failure grants nothing: the caller only calls on `solved`;
    - redoing the same exercise grants nothing -- the event id is
      "solved:<exercise>" and its primary key refuses the duplicate;
    - a replayed poll grants nothing: same id, same refusal.
    """
    event_id = "solved:" + entry["id"]
    granted = state.grant_first_solve(
        user, entry["id"], event_id, policy.xp_reussite(entry),
        "première réussite de l'exercice", policy.VERSION,
        {"job": job_id, "difficulty": entry.get("difficulty") or ""},
        policy.plafond_quotidien())
    if granted is None:
        return
    facts = progression_facts(user)
    if facts is not None:
        state.unlock(user, policy.succes_atteints(facts)
                     + cards_to_grant(user), event_id, policy.VERSION)


def enregistrer_verification(user, entry, job_id, reussi):
    """A verification verdict -> a piece of evidence, solved OR NOT.

    Written in both cases, and that is the point: without the trace of a
    failure, the "needs review" band would not exist and a skill attempted
    without success would be indistinguishable from one never attempted.

    NO XP IS EVER GRANTED HERE. A verification measures a capability; XP
    counts a practice activity. Mixing them would make verification farmable
    and XP indistinguishable from a grade (invariant 1).

    Nothing to recompute when the evidence already existed -- same replayed
    poll, same id, same refusal.
    """
    ecrit = state.record_event(
        user, "verification:%s:%s" % (entry["id"], job_id), VERIFICATION,
        entry["id"], policy.VERSION, {"job": job_id, "passed": bool(reussi)})
    if ecrit is None:
        return
    facts = progression_facts(user)
    if facts is not None:
        # A CARD FAMILY CAN INCLUDE A VERIFICATION, so cards are recomputed
        # here too. They still grant no XP -- `unlock` writes to
        # `achievement_unlocked`, and nothing in that table produces value.
        state.unlock(user, policy.succes_atteints(facts) + cards_to_grant(user),
                    "verification:" + entry["id"], policy.VERSION)


# --- The collection (design 1e) ----------------------------------------------
# A CARD IS AN ACHIEVEMENT WEARING ANOTHER COAT: same table, same primary key,
# same "once only", same `forget()`. What differs is the criterion (a family of
# exercises all solved) and the presentation (a grid rather than a list).
#
# NOTHING IS DRAWN AND NOTHING EXPIRES. The condition of a locked card is
# printed on the card: a collection whose rules one can read is the opposite of
# a loot box, and that is the line student-motivations.md draws.


def cards_to_grant(user):
    """The card ids this account has now earned. [] when the database is mute.

    Read from the SOLVED exercises of the PUBLISHED catalog: a card whose
    family is not fully open cannot be earned by accident, and one whose
    exercise was withdrawn stops being reachable rather than being revoked --
    `achievement_unlocked` is append-only, and an earned card stays earned.
    """
    states = state.read_states(user)
    if states is None:
        return []
    published = {e["id"] for e in exercices_ouverts()}
    solved = {row.get("exercise_id") for row in states
              if row.get("status") == "solved"} & published
    return policy.cards_earned(solved)


def collection_view(unlocked, rates, cohort):
    """[{id, name, family, condition, held, rarity}] -- every card, held or not.

    A LOCKED CARD IS SHOWN, WITH ITS CONDITION. Hiding it would turn the grid
    into a surprise, and a surprise is the mechanic this collection exists
    without.

    `rarity` IS AN OBSERVED RATE OR None, never a decreed tier. It is withheld
    under `policy.minimum_cohort()`: a percentage over four accounts
    describes those four accounts, which is the same disclosure the leaderboard
    threshold refuses.
    """
    held = {row["id"] for row in unlocked or ()}
    cohort = int(cohort or 0)
    views = []
    for key, card in policy.CARDS.items():
        holders = int((rates or {}).get(key, 0))
        views.append({
            "id": card["id"],
            "name": card["name"],
            "family": card["family"],
            "condition": card["condition"],
            "held": key in held,
            "rarity": (round(holders * 100 / cohort)
                       if cohort >= policy.minimum_cohort() else None),
        })
    return views


def progress_payload(entries, facts, states, practice, evidences,
                     practice_days=None):
    """GET /progres's contract: bounded, derived, and with nothing secret.

    No submitted code, no verdict detail, no test path: counters, public
    catalog ids, and the achievement labels the policy carries. `policy`
    travels with it, so a screen knows which version of the numbers it is
    speaking of.
    """
    touched, solved = exercise_facts(states, practice)
    pratique = exercices_pratique(entries)
    return {
        "policy": policy.VERSION,
        "xp": facts["xp"],
        "level": policy.niveau(facts["xp"]),
        "exercises": {
            "total": len(pratique),
            "practiced": sum(1 for e in pratique if e["id"] in touched),
            "solved": sum(1 for e in pratique if e["id"] in solved),
        },
        "skills": skills_view(pratique, touched, solved),
        # Bands travel ONCE, as a legend: the page must be able to say what
        # "needs review" means without rewriting it on its own side.
        "mastery": {
            "bands": [dict(bande) for bande in policy.BANDES.values()],
            "skills": maitrise_view(entries, evidences),
        },
        # A stored id the policy no longer defines is not displayed -- it is
        # not lost for that, it stays in the database.
        "achievements": [{"id": row["id"],
                    "title": policy.SUCCES[row["id"]]["title"],
                    "description": policy.SUCCES[row["id"]]["description"],
                    "unlocked_at": row["unlocked_at"]}
                   for row in facts["achievements"] if row["id"] in policy.SUCCES],
        # CARDS SHARE THE TABLE, NOT THE LIST. Both live in
        # `achievement_unlocked`; the `card:` prefix is what keeps a card out
        # of the achievements section and vice versa.
        "cards": sum(1 for row in facts["achievements"]
                     if row["id"] in policy.CARDS),
        "next": recommander(pratique, touched, solved),
        # THE PRACTICE CALENDAR (design 1b), and it replaces a streak on
        # purpose: a day with no square takes nothing away, so there is no
        # counter to break and none to defend. Derived from
        # `practice_attempt`, never stored.
        "practice_days": practice_days or [],
        # The display/export of grants, already bounded by state.py.
        "transactions": facts["transactions"],
    }
