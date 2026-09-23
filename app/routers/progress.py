import headers
import policy
import state
from deps import Sub
from fastapi import APIRouter
from services import progress
from services.catalog import open_exercises

router = APIRouter(tags=["progress"])

CALENDAR_DAYS = 91


@router.get("/progress")
def get_progress(sub: Sub):
    facts = state.read_progress(sub)
    statuses = state.read_states(sub)
    practice = state.read_practice_summary(sub)
    evidences = state.read_events(sub, progress.VERIFICATION)
    days = state.read_practice_days(sub, CALENDAR_DAYS)
    if (facts is None or statuses is None or practice is None
            or evidences is None or days is None):
        return headers.error(503, "db_down")
    return progress.progress_payload(open_exercises(), facts,
                                     statuses, practice, evidences, days)


@router.get("/collection")
def collection(sub: Sub):
    facts = state.read_progress(sub)
    unlock_rates = state.read_unlock_rates()
    if facts is None or unlock_rates is None:
        return headers.error(503, "db_down")
    rates, cohort = unlock_rates
    return {"policy": policy.VERSION,
            "cards": progress.collection_view(facts["achievements"], rates, cohort),
            "cohort": cohort}
