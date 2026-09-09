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

import config
import policy
import state
import headers
import security
from deps import Sub
from fastapi import APIRouter, Query
from services import leaderboard

router = APIRouter(tags=["leaderboard"])


@router.get("/leaderboard")
def read_leaderboard(sub: Sub, scope: str = Query("group"),
                     group: int | None = Query(None)):
    """This account's ranking: its group by default, the whole course on ask.

    THE GROUP COMES FROM THE PROFILE, never from the query string: `?group=6`
    would let anyone read a cohort they are not in, and a cohort of strangers
    is exactly what the minimum-cohort rule exists to prevent.

    ONE EXCEPTION, AND IT IS RECOMPUTED SERVER-SIDE: a moderator may name a
    group. For them the reason above evaporates -- they already read every
    thread of every group -- and "see how section 04 is doing" is the whole
    point of giving an instructor a ranking. A `?group=` from anyone else is
    IGNORED, not refused: it is a convenience parameter, and a 403 would make
    a shared link look like an outage.

    THE INSTRUCTOR READS IT AND NEVER APPEARS IN IT. That exclusion is not
    here -- it is the `WHERE` of `state.leaderboard_rows`, next to the opt-in,
    because fairness must not depend on a router remembering to filter.

    THE MINIMUM COHORT STILL APPLIES TO THEM. It is what keeps a table from
    describing four identifiable people, and the instructor is precisely the
    person who could tie aliases to faces over a term. A group under the
    threshold yields no table, for anybody.
    """
    profile = state.forum_profil(sub)
    if profile is None:
        return headers.erreur(503, "la base ne répond pas")
    moderator = security.is_moderator(sub)
    if scope == "course":
        wanted = None
    elif moderator and group is not None:
        wanted = group
    else:
        wanted = profile.get("group_number")
    staff = config.FORUM_MODERATORS
    rows = state.leaderboard_rows(wanted, leaderboard.WINDOW_DAYS, staff)
    if rows is None:
        return headers.erreur(503, "la base ne répond pas")
    payload = leaderboard.leaderboard_view(rows, sub, wanted)
    payload["scope"] = "course" if wanted is None else "group"
    payload["group"] = wanted
    # PAS D'ALIAS POUR UN MODÉRATEUR : le `WHERE` l'exclut du tableau, donc
    # renvoyer « tu apparais sous X » serait la charge qui contredit la
    # requête. On supprime la contradiction à la source plutôt que de compter
    # sur la page pour ne pas l'afficher.
    payload["alias"] = "" if moderator else (profile.get("alias") or "")
    # THE PAGE MUST NOT SAY "you appear as X" TO SOMEONE THE `WHERE` EXCLUDES.
    # It is the server that knows, so it is the server that says so.
    payload["moderator"] = moderator
    payload["groups"] = list(config.FORUM_GROUPES) if moderator else []
    # THE DIVISIONS ARE READ ON THE WHOLE COURSE, always: they are a picture
    # of the cohort, and a picture of one group of four would be a picture of
    # four people.
    everyone = (state.leaderboard_rows(None, leaderboard.WINDOW_DAYS, staff)
                if wanted is not None else rows)
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
