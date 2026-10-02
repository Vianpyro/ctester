import policy
import state
from services.catalog import open_collections, open_exercises, published_cards

MAX_SKILLS = 40

# Long enough to count every practice day a student ever had.
ALL_DAYS = 3650

# A solve that took this many tests counts as perseverance.
PERSEVERED_AFTER = 5

VERIFICATION = "VerificationEvaluated"


def practice_exercises(entries):
    """Verifications and team assignments never count as practice."""
    return [entry for entry in entries
            if not entry.get("verification") and not entry.get("assignment")]


def verifications(entries):
    return [entry for entry in entries if entry.get("verification")]


def exercise_facts(states, practice):
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
    skills = set()
    for entry in entries:
        if entry["id"] in touched:
            skills.update(entry.get("skills") or ())
    return skills


def recommend(entries, touched, solved):
    known = practised_skills(entries, touched)
    remaining = [e for e in entries if e["id"] not in solved]
    for entry in remaining:
        for skill in entry.get("skills") or ():
            if skill in known:
                return {"exercise_id": entry["id"], "skill": skill}
    if remaining:
        return {"exercise_id": remaining[0]["id"], "skill": None}
    return None


def latest_attempts(evidences):
    last = {}
    for row in evidences or ():
        exercise = (row or {}).get("exercise_id")
        if exercise and exercise not in last:
            last[exercise] = bool((row.get("payload") or {}).get("passed"))
    return last


def comebacks(evidences):
    """Verifications passed after a failed attempt. Evidences come newest first."""
    passed, back = set(), set()
    for row in evidences or ():
        exercise = (row or {}).get("exercise_id")
        if not exercise:
            continue
        if ((row or {}).get("payload") or {}).get("passed"):
            passed.add(exercise)
        elif exercise in passed:
            back.add(exercise)
    return back


def solved_verifications(evidences):
    return {(row or {})["exercise_id"] for row in evidences or ()
            if (row or {}).get("exercise_id")
            and ((row or {}).get("payload") or {}).get("passed")}


def mastery_view(entries, evidences):
    last = latest_attempts(evidences)
    order, table = [], {}
    for entry in verifications(entries):
        attempt = last.get(entry["id"])
        for skill in entry.get("skills") or ():
            row = table.get(skill)
            if row is None:
                row = table[skill] = {"id": skill, "total": 0,
                                      "attempted": 0, "passed": 0}
                order.append(row)
            row["total"] += 1
            row["attempted"] += int(attempt is not None)
            row["passed"] += int(attempt is True)
    for row in order:
        row["band"] = policy.mastery_band(row["passed"], row["attempted"],
                                           row["total"])
    return order[:MAX_SKILLS]


def progression_facts(user):
    states = state.read_states(user)
    practice = state.read_practice_summary(user)
    evidences = state.read_events(user, VERIFICATION)
    days = state.read_practice_days(user, ALL_DAYS)
    if states is None or practice is None or evidences is None or days is None:
        return None
    return count_facts(open_exercises(), states, practice, evidences, len(days),
                       open_collections(), published_cards())


def count_facts(entries, states, practice, evidences, days=0, collections=(), cards=()):
    """Every fact an achievement can count, named by its "on". All generic: no id is named."""
    exercises = practice_exercises(entries)
    touched, solved = exercise_facts(states, practice)
    published = {e["id"] for e in exercises}
    done = [e for e in exercises if e["id"] in solved]
    verifiable = {e["id"] for e in verifications(entries)}
    opened = {e["id"] for e in entries}
    attempts = {row.get("exercise_id"): int(row.get("attempts") or 0) for row in practice or ()}
    labs = [published.intersection(c.get("items") or ()) for c in collections or ()]
    return {
        "practiced": len(touched & published),
        "solved": len(done),
        "complete": int(bool(published) and published <= solved),
        "labs": sum(1 for items in labs if items and items <= solved),
        "solved_io": sum(1 for e in done if e.get("mode") == "io"),
        "solved_unity": sum(1 for e in done if e.get("mode") == "unity"),
        "solved_quiz": sum(1 for e in done if e.get("mode") == "quiz"),
        "solved_intermediate": sum(1 for e in done if e.get("difficulty") == "intermediate"),
        "solved_advanced": sum(1 for e in done if e.get("difficulty") == "advanced"),
        "solved_bonus": sum(1 for e in done if e.get("bonus")),
        "skills": len(practised_skills(exercises, touched)),
        "verifications": len(solved_verifications(evidences) & verifiable),
        "skills_verified": sum(1 for row in mastery_view(entries, evidences)
                               if row["band"] == "verifie"),
        "comebacks": len(comebacks(evidences) & verifiable),
        "persevered": sum(1 for e in done if attempts.get(e["id"], 0) >= PERSEVERED_AFTER),
        "tests": sum(n for exercise, n in attempts.items() if exercise in opened),
        "days": int(days or 0),
        "cards": len(policy.cards_earned(solved & opened, cards)),
    }


def ceilings(entries, collections=(), cards=()):
    """The most each fact can reach with what is published: what no one can earn is hidden."""
    plenty = 10 ** 6
    ids = [e["id"] for e in entries]
    evidences = [row for e in verifications(entries) for row in (
        {"exercise_id": e["id"], "payload": {"passed": True}},
        {"exercise_id": e["id"], "payload": {"passed": False}})]
    return count_facts(entries, [{"exercise_id": i, "status": "solved"} for i in ids],
                       [{"exercise_id": i, "attempts": plenty, "successes": 1} for i in ids],
                       evidences, plenty, collections, cards)


def reward(user, entry, job_id):
    # The event id is the idempotency key: one grant per account and exercise.
    event_id = "solved:" + entry["id"]
    granted = state.grant_first_solve(
        user, entry["id"], event_id, policy.xp_for_solve(entry),
        "première réussite de l'exercice", policy.VERSION,
        {"job": job_id, "difficulty": entry.get("difficulty") or ""},
        policy.daily_cap())
    if granted is None:
        return practice(user, job_id)
    return _unlock(user, event_id)


def practice(user, job_id):
    # Tests and practice days count even when nothing is solved.
    return _unlock(user, "practice:" + job_id)


def record_verification(user, entry, job_id, solved):
    # One fact per job, failures included: the "to consolidate" band depends on them.
    written = state.record_event(
        user, "verification:%s:%s" % (entry["id"], job_id), VERIFICATION,
        entry["id"], policy.VERSION, {"job": job_id, "passed": bool(solved)})
    if written is None:
        return []
    return _unlock(user, "verification:" + entry["id"])


def _unlock(user, event_id):
    """What this fact unlocked, so the verdict can show it once."""
    facts = progression_facts(user)
    if facts is None:
        return []
    return state.unlock(user, policy.achievements_reached(facts) + cards_to_grant(user),
                        event_id, policy.VERSION) or []


def catch_up(user):
    # Achievements a newer policy added, or reached before a verdict counted them,
    # are unlocked when the student looks rather than at their next test.
    return _unlock(user, "recount")


def cards_to_grant(user):
    states = state.read_states(user)
    if states is None:
        return []
    published = {e["id"] for e in open_exercises()}
    solved = {row.get("exercise_id") for row in states
              if row.get("status") == "solved"} & published
    return policy.cards_earned(solved, published_cards())


def collection_view(unlocked, rates, cohort, solved=()):
    held = {row["id"] for row in unlocked or ()}
    solved = set(solved or ()) & {e["id"] for e in open_exercises()}
    cohort = int(cohort or 0)
    views = []
    for key, card in policy.cards_by_key(published_cards()).items():
        holders = int((rates or {}).get(key, 0))
        views.append({
            "id": card["id"],
            "name": card["name"],
            "family": card["family"],
            "art": card.get("art") or card.get("family") or "",
            "condition": card["condition"],
            "held": key in held,
            "progress": len(solved.intersection(card.get("exercises") or ())),
            "needed": len(card.get("exercises") or ()),
            "rarity": (round(holders * 100 / cohort)
                       if cohort >= policy.minimum_cohort() else None),
        })
    return views


def achievements_view(unlocked, counts, ceiling):
    """Every achievement earned, or still within reach of the published content."""
    when = {row["id"]: row["unlocked_at"] for row in unlocked or ()}
    return [{"id": a["id"], "unlocked_at": when.get(a["id"]),
             "count": min(counts.get(a["on"], 0), a["threshold"]),
             "threshold": a["threshold"]}
            for a in policy.POLICY["achievements"]
            if a["id"] in when or ceiling.get(a["on"], 0) >= a["threshold"]]


def progress_payload(entries, facts, states, practice, evidences,
                     practice_days=None, days=0, collections=(), cards=()):
    touched, solved = exercise_facts(states, practice)
    exercises = practice_exercises(entries)
    return {
        "policy": policy.VERSION,
        "xp": facts["xp"],
        "level": policy.level(facts["xp"]),
        "exercises": {
            "total": len(exercises),
            "practiced": sum(1 for e in exercises if e["id"] in touched),
            "solved": sum(1 for e in exercises if e["id"] in solved),
        },
        "skills": skills_view(exercises, touched, solved),
        "mastery": {
            "bands": [dict(band) for band in policy.BANDS.values()],
            "skills": mastery_view(entries, evidences),
        },
        "achievements": achievements_view(
            facts["achievements"],
            count_facts(entries, states, practice, evidences, days, collections, cards),
            ceilings(entries, collections, cards)),
        "cards": sum(1 for row in facts["achievements"]
                     if row["id"] in policy.cards_by_key(published_cards())),
        "next": recommend(exercises, touched, solved),
        "practice_days": practice_days or [],
        "transactions": facts["transactions"],
    }
