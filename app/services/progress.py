import policy
import state
from services.catalog import open_exercises, published_cards

MAX_SKILLS = 40

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
    if states is None or practice is None or evidences is None:
        return None
    entries = open_exercises()
    exercises = practice_exercises(entries)
    touched, solved = exercise_facts(states, practice)
    published = {e["id"] for e in exercises}
    verifiable = {e["id"] for e in verifications(entries)}
    return {"solved": len(solved & published),
            "skills": len(practised_skills(exercises, touched)),
            "verifications": len(solved_verifications(evidences) & verifiable)}


def reward(user, entry, job_id):
    # The event id is the idempotency key: one grant per account and exercise.
    event_id = "solved:" + entry["id"]
    granted = state.grant_first_solve(
        user, entry["id"], event_id, policy.xp_for_solve(entry),
        "première réussite de l'exercice", policy.VERSION,
        {"job": job_id, "difficulty": entry.get("difficulty") or ""},
        policy.daily_cap())
    if granted is None:
        return
    facts = progression_facts(user)
    if facts is not None:
        state.unlock(user, policy.achievements_reached(facts)
                     + cards_to_grant(user), event_id, policy.VERSION)


def record_verification(user, entry, job_id, solved):
    # One fact per job, failures included: the "to consolidate" band depends on them.
    written = state.record_event(
        user, "verification:%s:%s" % (entry["id"], job_id), VERIFICATION,
        entry["id"], policy.VERSION, {"job": job_id, "passed": bool(solved)})
    if written is None:
        return
    facts = progression_facts(user)
    if facts is not None:
        state.unlock(user, policy.achievements_reached(facts) + cards_to_grant(user),
                    "verification:" + entry["id"], policy.VERSION)


def cards_to_grant(user):
    states = state.read_states(user)
    if states is None:
        return []
    published = {e["id"] for e in open_exercises()}
    solved = {row.get("exercise_id") for row in states
              if row.get("status") == "solved"} & published
    return policy.cards_earned(solved, published_cards())


def collection_view(unlocked, rates, cohort):
    held = {row["id"] for row in unlocked or ()}
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
            "rarity": (round(holders * 100 / cohort)
                       if cohort >= policy.minimum_cohort() else None),
        })
    return views


def progress_payload(entries, facts, states, practice, evidences,
                     practice_days=None):
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
        "achievements": [{"id": row["id"],
                    "title": policy.ACHIEVEMENTS[row["id"]]["title"],
                    "description": policy.ACHIEVEMENTS[row["id"]]["description"],
                    "unlocked_at": row["unlocked_at"]}
                   for row in facts["achievements"] if row["id"] in policy.ACHIEVEMENTS],
        "cards": sum(1 for row in facts["achievements"]
                     if row["id"] in policy.cards_by_key(published_cards())),
        "next": recommend(exercises, touched, solved),
        "practice_days": practice_days or [],
        "transactions": facts["transactions"],
    }
