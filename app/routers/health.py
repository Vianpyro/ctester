import time

import config
import deps
import security
from fastapi import APIRouter, Query, Request
from services import forum as forum_service

router = APIRouter(tags=["health"])


@router.get("/healthz")
@router.head("/healthz")
def healthz() -> dict[str, bool]:
    return {"ok": True}


@router.get("/live")
def live(request: Request, id: str = Query("")):
    who = (id or security.client_id(request.headers, deps.tcp_peer(request)))[:64]
    with deps.lock:
        n = deps.presence.touch(who, time.time())
    return {"n": n}


@router.get("/oidc.json")
def oidc():
    if not security.oidc_enabled():
        return {}
    return {"issuer": config.OIDC_ISSUER, "client_id": config.OIDC_CLIENT_ID,
            "forum": forum_service.forum_enabled(),
            "discord": config.DISCORD_URL,
            "scratch": config.SCRATCH}
