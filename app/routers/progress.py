"""An account's progression: XP, level, skills, achievements, recommendation,
the practice calendar, and the collection.

NOTHING IS COMPUTED BY THE BROWSER. Everything arrives ready-made from these
routes, which recompute their projection on every call from three append-only
fact tables and the public catalog. A page that computed its own XP would be a
page where one gives it to oneself from the console.

A MISSING PROJECTION IS NOT A ZERO. Database down: 503 and no number.
Announcing "0 XP" during an outage tells someone their work is gone.

ponytail: seven serialized SQL round trips behind `state.py`'s single lock.
Grouping them into one read is doable and not done -- at 80 students the
queue behind that lock is empty, and one grouped query is harder to read
back. The threshold is a p95 of this route above one second, which
`load_test.py` reports on its own.
"""

import state
import policy
import headers
from deps import Sub
from fastapi import APIRouter
from services import progress
from services.catalog import exercices_ouverts

router = APIRouter(tags=["progression"])

# THIRTEEN WEEKS OF SQUARES, which is a term. Long enough that the shape of
# someone's habits shows, short enough that the strip fits a laptop without
# scrolling -- and it is a display bound, not a retention rule: nothing is
# deleted past it.
CALENDAR_DAYS = 91


@router.get("/progres")
def progres(sub: Sub):
    faits = state.read_progress(sub)
    etats = state.read_states(sub)
    pratique = state.read_practice_summary(sub)
    # Mastery evidence, treated like the rest: mute -> 503, never a "not yet
    # verified" band that would be an outage's zero in disguise.
    evidences = state.read_events(sub, progress.VERIFICATION)
    days = state.read_practice_days(sub, CALENDAR_DAYS)
    if (faits is None or etats is None or pratique is None
            or evidences is None or days is None):
        return headers.erreur(503, "la base ne répond pas")
    return progress.progress_payload(exercices_ouverts(), faits,
                                     etats, pratique, evidences, days)


@router.get("/collection")
def collection(sub: Sub):
    """Every card, held or not, with its condition and its observed rarity.

    A SEPARATE ROUTE FROM `/progres`, and deliberately: the collection is its
    own screen, opened rarely, and its rarity read scans a table the
    progression screen has no use for. Folding it in would make every visit to
    "Mes progrès" pay for a grid nobody asked to see.
    """
    facts = state.read_progress(sub)
    unlock_rates = state.read_unlock_rates()
    if facts is None or unlock_rates is None:
        return headers.erreur(503, "la base ne répond pas")
    rates, cohort = unlock_rates
    return {"policy": policy.VERSION,
            "cards": progress.collection_view(facts["achievements"], rates, cohort),
            "cohort": cohort}
