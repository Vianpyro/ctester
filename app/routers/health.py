import time

import config
import deps
import security
from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse
from services import forum as forum_service
from services import maintenance

router = APIRouter(tags=["health"])


@router.get("/healthz")
@router.head("/healthz")
def healthz() -> dict[str, bool]:
    return {"ok": True}


@router.get("/live")
def live(request: Request, id: str = Query("")):
    # The window id only refines the caller's own key, never replaces it: on its own it
    # let anyone mint entries under any name, including the one ctester-pull deploys on.
    who = security.client_id(request.headers, deps.tcp_peer(request), station=id[:64])
    with deps.lock:
        n = deps.presence.touch(who, time.time())
    return {"n": n}


@router.get("/events")
async def events():
    # async: a def would hold a threadpool thread for as long as each tab stays open.
    return StreamingResponse(maintenance.stream(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache",
        # Nginx buffers proxied responses by default; this turns it off for this one.
        "X-Accel-Buffering": "no",
    })


@router.get("/oidc.json")
def oidc():
    if not security.oidc_enabled():
        return {}
    return {"issuer": config.OIDC_ISSUER, "client_id": config.OIDC_CLIENT_ID,
            "forum": forum_service.forum_enabled(),
            "discord": config.DISCORD_URL,
            "scratch": config.SCRATCH}
