import secrets
import uuid

import config
import headers
import security
import state
from deps import Sub
from fastapi import APIRouter, Query
from services import leaderboard

router = APIRouter(tags=["leaderboard"])


@router.get("/leaderboard")
def read_leaderboard(sub: Sub, scope: str = Query("group"),
                     group: int | None = Query(None)):
    profile = state.forum_profile(sub)
    if profile is None:
        return headers.error(503, "la base ne répond pas")
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
        return headers.error(503, "la base ne répond pas")
    payload = leaderboard.leaderboard_view(rows, sub, wanted, reader=moderator)
    payload["scope"] = "course" if wanted is None else "group"
    payload["group"] = wanted
    payload["alias"] = "" if moderator else (profile.get("alias") or "")
    payload["moderator"] = moderator
    payload["groups"] = list(config.FORUM_GROUPS) if moderator else []
    everyone = (state.leaderboard_rows(None, leaderboard.WINDOW_DAYS, staff)
                if wanted is not None else rows)
    payload["divisions"] = leaderboard.divisions_view(everyone or [])
    return payload


@router.post("/leaderboard/alias")
def redraw_alias(sub: Sub):
    profile = state.forum_profile(sub)
    taken = state.forum_taken_aliases()
    if profile is None or taken is None:
        return headers.error(503, "la base ne répond pas")
    alias = leaderboard.draw_alias(taken, secrets.randbelow(1 << 32))
    if alias is None:
        return headers.error(503, "plus de pseudonyme disponible")
    if not _write(sub, profile, alias=alias):
        return headers.error(503, "la base ne répond pas")
    return {"alias": alias}


def _write(sub, profile, **changes):
    values = dict(profile, **changes)
    return state.forum_write_profile(
        uuid.uuid4().hex, sub, values.get("display_name"),
        values.get("group_number"), values.get("display_name_public"),
        values.get("group_number_public"), alias=values.get("alias"),
        plate_frame=values.get("plate_frame"),
        badges_public=values.get("badges_public"),
        leaderboard_opt_in=values.get("leaderboard_opt_in"))
