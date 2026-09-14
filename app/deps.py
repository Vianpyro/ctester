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


class Refusal(Exception):
    def __init__(self, code, message, **extra):
        super().__init__(message)
        self.code = code
        self.message = message
        self.extra = extra


def user(request: Request) -> str:
    if not security.oidc_enabled():
        raise Refusal(503, "la persistance n'est pas configurée")
    sub = security.current_user(request.headers)
    if sub is None:
        raise Refusal(401, "connexion requise ou expirée")
    return sub


def forum_user(request: Request) -> str:
    if not forum_service.forum_enabled():
        raise Refusal(503, "les discussions ne sont pas activées sur ce déploiement")
    return user(request)


def moderator(request: Request) -> str:
    sub = forum_user(request)
    if not security.is_moderator(sub):
        raise Refusal(403, "réservé à l'enseignant")
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
        raise Refusal(429, f"trop d'écritures -- réessaie dans {wait} s",
                      retry_after=wait)


def throttle_forum(sub: str) -> None:
    with lock:
        wait = forum_quota.check(sub, time.time())
    if wait:
        raise Refusal(429, f"trop de messages d'un coup -- réessaie dans {wait} s",
                      retry_after=wait)


def tcp_peer(request: Request) -> str:
    return request.client.host if request.client else ""
