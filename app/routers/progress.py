import headers
import policy
import state
from deps import Sub
from fastapi import APIRouter
from services import progress
from services.catalog import (open_collections, open_exercises, published_achievements,
                              published_cards)

router = APIRouter(tags=["progress"])

CALENDAR_DAYS = 91


def _with_unlocked(payload, fresh):
    return dict(payload, unlocked=fresh) if fresh else payload


@router.get("/progress")
def get_progress(sub: Sub):
    fresh = progress.catch_up(sub)
    facts = state.read_progress(sub)
    statuses = state.read_states(sub)
    practice = state.read_practice_summary(sub)
    evidences = state.read_events(sub, progress.VERIFICATION)
    days = state.read_practice_days(sub, CALENDAR_DAYS)
    every_day = state.read_practice_days(sub, progress.ALL_DAYS)
    if (facts is None or statuses is None or practice is None
            or evidences is None or days is None or every_day is None):
        return headers.error(503, "db_down")
    return _with_unlocked(progress.progress_payload(
        open_exercises(), facts, statuses, practice, evidences, days,
        len(every_day), open_collections(), published_cards(),
        published_achievements()), fresh)


@router.get("/collection")
def collection(sub: Sub):
    fresh = progress.catch_up(sub)
    facts = state.read_progress(sub)
    statuses = state.read_states(sub)
    unlock_rates = state.read_unlock_rates()
    achievements = progress.user_achievements(sub, facts and facts["achievements"])
    if facts is None or statuses is None or unlock_rates is None or achievements is None:
        return headers.error(503, "db_down")
    rates, cohort = unlock_rates
    solved = {row["exercise_id"] for row in statuses if row.get("status") == "solved"}
    return _with_unlocked({"policy": policy.VERSION,
                           "cards": progress.collection_view(facts["achievements"], rates,
                                                             cohort, solved),
                           "achievements": progress.with_rarity(achievements, rates, cohort),
                           "cohort": cohort}, fresh)
