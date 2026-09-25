import asyncio
import json
import time
from threading import Lock
from typing import Annotated

import config
import security
from fastapi import Depends, Request
from services import forum as forum_service
from services import quotas

lock = Lock()
quota = quotas.Quota(config.COOLDOWN, config.HOURLY)
signed_in_quota = quotas.Quota(config.COOLDOWN_SIGNED_IN, config.HOURLY)
state_quota = quotas.Quota(cooldown=1, hourly=1200)
forum_quota = quotas.Quota(config.FORUM_COOLDOWN, config.FORUM_HOURLY)
scratch_quota = quotas.Quota(config.SCRATCH_COOLDOWN, config.SCRATCH_HOURLY)
presence = quotas.Presence()

CLOSE_UNAUTHORIZED = 4401
CLOSE_FORBIDDEN = 4403
CLOSE_BUSY = 4429
CLOSE_BAD = 4400
CLOSE_UNAVAILABLE = 4503

HELLO_TIMEOUT = 10


async def hello(socket, max_frame):
    """The opening frame every live socket shares. The token travels in it because a browser
    cannot set Authorization on a WebSocket and a token in the URL would reach proxy logs.
    Returns None once the socket has been closed, so the caller only has to return."""
    origin = socket.headers.get("origin", "").strip().rstrip("/")
    if origin and origin not in config.ORIGINS:
        await socket.close(code=CLOSE_FORBIDDEN)
        return None
    await socket.accept()
    try:
        raw = await asyncio.wait_for(socket.receive_text(), timeout=HELLO_TIMEOUT)
    except Exception:
        await socket.close(code=CLOSE_BAD)
        return None
    if len(raw) > max_frame:
        await socket.close(code=CLOSE_BAD)
        return None
    try:
        opening = json.loads(raw)
    except ValueError:
        opening = None
    if not isinstance(opening, dict) or opening.get("t") != "hello":
        await socket.close(code=CLOSE_BAD)
        return None
    return opening


class Refusal(Exception):
    def __init__(self, code, message, **extra):
        super().__init__(message)
        self.code = code
        self.message = message
        self.extra = extra


def user(request: Request) -> str:
    if not security.oidc_enabled():
        raise Refusal(503, "no_persistence")
    try:
        sub = security.current_user(request.headers, strict=True)
    except security.AuthUnavailable:
        raise Refusal(503, "auth_unavailable") from None
    if sub is None:
        raise Refusal(401, "sign_in_required")
    return sub


def forum_user(request: Request) -> str:
    if not forum_service.forum_enabled():
        raise Refusal(503, "forum_disabled")
    return user(request)


def moderator(request: Request) -> str:
    sub = forum_user(request)
    if not security.is_moderator(sub):
        raise Refusal(403, "teachers_only")
    return sub


def preview(request: Request) -> bool:
    """Unlike the other dependencies this never raises: it guards anonymous routes."""
    return security.is_moderator(security.current_user(request.headers))


Sub = Annotated[str, Depends(user)]
SubForum = Annotated[str, Depends(forum_user)]
SubModerator = Annotated[str, Depends(moderator)]
Preview = Annotated[bool, Depends(preview)]


def throttle_write(request: Request) -> None:
    who = security.client_id(request.headers, tcp_peer(request))
    with lock:
        wait = state_quota.check(who, time.time())
    if wait:
        raise Refusal(429, "too_many_writes", params={"wait": wait},
                      retry_after=wait)


def throttle_forum(sub: str) -> None:
    with lock:
        wait = forum_quota.check(sub, time.time())
    if wait:
        raise Refusal(429, "too_many_messages", params={"wait": wait},
                      retry_after=wait)


def tcp_peer(request: Request) -> str:
    return request.client.host if request.client else ""
