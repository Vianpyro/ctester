"""Health, presence, and what this deployment offers.

The three routes the page queries before it knows what to draw. None of them
requires a token -- `/oidc.json` must answer an anonymous visitor, or the page
would never know a sign-in button exists.
"""

import time

import config
import deps
import security
from fastapi import APIRouter, Query, Request
from services import forum as forum_service

router = APIRouter(tags=["sante"])


@router.get("/healthz")
def healthz() -> dict[str, bool]:
    """What the container's `healthcheck` queries every 30 s.

    IT TOUCHES NEITHER THE DATABASE NOR THE SPOOL, and that is intentional: it
    answers "this process serves HTTP", not "the whole chain is fine". A
    `/healthz` that queried Postgres would restart the web container in a loop
    on the first database outage -- while the anonymous path still works
    perfectly well.
    """
    return {"ok": True}


@router.get("/live")
def live(request: Request, id: str = Query("")):
    """How many windows are open, to the minute.

    THE ONLY EXCEPTION TO "THE ANONYMOUS VISITOR EMITS NO REQUEST", and it is
    a deliberate one: the heartbeat goes to an in-memory `dict`, never to the
    database or to an account, and carries no token.

    `id` COMES FROM THE BROWSER (drawn at random, kept for the life of the
    tab), so it is falsifiable and unauthenticated: it is a displayed number,
    not a control. Without it we fall back to the IP -- a whole school then
    counts as one window, which is wrong but exposes nothing.

    TRUNCATED AT 64, NOT REFUSED PAST IT. A `max_length` on the parameter
    would make this respond 400 to an overlong token: it would be the only
    anonymous route able to fail, for a display counter. `battement()`
    swallows the error and the counter stays hidden -- but a silent failure is
    still a failure.
    """
    qui = (id or security.client_id(request.headers, deps.pair_tcp(request)))[:64]
    with deps.verrou:
        n = deps.presence.touch(qui, time.time())
    return {"n": n}


@router.get("/oidc.json")
def oidc():
    """What this deployment offers. An empty object means "nothing more".

    The page queries it before displaying anything: without `issuer`, the
    whole sign-in block stays inert and the anonymous path is exactly what it
    was. `forum` travels here because this is already the "what is offered"
    endpoint -- false or absent, the button does not exist and `forum.js` is
    never requested.
    """
    if not security.oidc_enabled():
        return {}
    return {"issuer": config.OIDC_ISSUER, "client_id": config.OIDC_CLIENT_ID,
            "forum": forum_service.forum_enabled()}
