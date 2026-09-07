"""The optional leaderboard: one route to read it, one to redraw one's alias.

IT IS OPT-IN, AND THE OPT-IN LIVES ON THE PROFILE (`POST /forum/profil`), not
here: joining a ranking is an identity setting, next to "show my name" and
"show my group", and putting it anywhere else would make consent a thing one
gives twice in two places that can disagree.

NO `sub` CROSSES THE BOUNDARY. `services/leaderboard.py` uses the `account`
column to find the caller's own row and drops it -- exactly as `forum_vue()`
does for a thread. What comes out is a drawn alias, a rank and a count.

NOBODY IS NAMED LAST, and under a minimum cohort there is no table at all.
Both rules are in the service, exercised by direct call.
"""

import secrets
import uuid

import policy
import state
import headers
from deps import Sub
from fastapi import APIRouter, Query
from services import leaderboard

router = APIRouter(tags=["leaderboard"])


@router.get("/leaderboard")
def read_leaderboard(sub: Sub, scope: str = Query("group")):
    """This account's ranking: its group by default, the whole course on ask.

    THE GROUP COMES FROM THE PROFILE, never from the query string: `?group=6`
    would let anyone read a cohort they are not in, and a cohort of strangers
    is exactly what the minimum-cohort rule exists to prevent.
    """
    profile = state.forum_profil(sub)
    if profile is None:
        return headers.erreur(503, "la base ne répond pas")
    group = None if scope == "course" else profile.get("group_number")
    rows = state.leaderboard_rows(group, leaderboard.WINDOW_DAYS)
    if rows is None:
        return headers.erreur(503, "la base ne répond pas")
    payload = leaderboard.leaderboard_view(rows, sub, group)
    payload["scope"] = "course" if group is None else "group"
    payload["alias"] = profile.get("alias") or ""
    # THE DIVISIONS ARE READ ON THE WHOLE COURSE, always: they are a picture
    # of the cohort, and a picture of one group of four would be a picture of
    # four people.
    everyone = (state.leaderboard_rows(None, leaderboard.WINDOW_DAYS)
                if group is not None else rows)
    payload["divisions"] = leaderboard.divisions_view(everyone or [])
    return payload


@router.post("/leaderboard/alias")
def redraw_alias(sub: Sub):
    """Draw another alias. As often as one likes, and that is the point.

    A NAME ONE CANNOT CHANGE IS A NAME ONE IS STUCK WITH, and a ranking is
    exactly where that matters. The draw is server-side from a CLOSED
    vocabulary (`policy.possible_aliases()`): nothing a student typed can ever
    reach a leaderboard, so there is no ranking to moderate.

    THE PREVIOUS ALIAS STAYS IN THE JOURNAL -- `forum_profile` is append-only
    -- which is what keeps a report readable after its subject redrew.
    """
    profile = state.forum_profil(sub)
    taken = state.forum_taken_aliases()
    if profile is None or taken is None:
        return headers.erreur(503, "la base ne répond pas")
    # THE CURRENT ALIAS STAYS IN THE TAKEN SET, so the draw cannot hand back
    # the same one: a button called "Un autre nom" that sometimes returns the
    # same name is a button that looks broken. Nobody else holds it, so
    # excluding it costs one candidate out of three hundred.
    alias = leaderboard.draw_alias(taken, secrets.randbelow(1 << 32))
    if alias is None:
        return headers.erreur(503, "plus de pseudonyme disponible")
    if not _write(sub, profile, alias=alias):
        return headers.erreur(503, "la base ne répond pas")
    return {"alias": alias}


def _write(sub, profile, **changes):
    """Rewrite the profile with one field changed. Append-only, so all of it.

    THE WHOLE PROFILE IS REWRITTEN because the latest row IS the profile: a
    partial write would silently reset the fields it left out, and the field
    it would reset most often is a visibility checkbox.
    """
    values = dict(profile, **changes)
    return state.forum_profil_ecrire(
        uuid.uuid4().hex, sub, values.get("display_name"),
        values.get("group_number"), values.get("display_name_public"),
        values.get("group_number_public"), alias=values.get("alias"),
        plate_frame=values.get("plate_frame"),
        badges_public=values.get("badges_public"),
        leaderboard_opt_in=values.get("leaderboard_opt_in"))
