"""Dependencies shared by the routers: who is calling, and how fast.

THREE GATES, AND NONE READS AN ID FROM THE REQUEST:

    Sub            an authenticated account
    SubForum       same, and the forum is enabled on this deployment
    SubModerateur  same, and this `sub` is on the moderation list

`security.current_user()` is the only source of identity in the whole
application. A route that accepted an `account` in its body would let anyone
write into anyone else's state -- that is the property these three aliases
exist to make hard to bypass.

THE COUNTERS ARE MODULE GLOBALS, ON PURPOSE: tests replace them
(`deps.forum_quota = quotas.Quota(...)`) to exercise a cap without waiting an
hour. The functions below read them by their module name, never through a
copy captured at import time -- a copy would make that replacement silent.
"""

import time
from threading import Lock
from typing import Annotated

import config
import security
from fastapi import Depends, Request
from services import forum as forum_service
from services import quotas

# The counters' lock. ONE, global, and that is enough: these are `dict`
# accesses, and the API runs with a single worker.
verrou = Lock()

# The SUBMISSION quota: a compilation costs one core on the Dell.
quota = quotas.Quota(config.COOLDOWN, config.HOURLY)

# THE SAME HOURLY CAP, A SHORTER WINDOW. An account identifies a student; the
# anonymous visitor is counted by a station their browser declares, so it is
# more easily replayed by opening a fresh profile. Two separate counters,
# never one with an `if`: a student's hourly quota must not change depending
# on whether they signed in midway through a session.
quota_connecte = quotas.Quota(config.COOLDOWN_CONNECTE, config.HOURLY)

# Saving a draft or a theme compiles nothing -- no container, no gcc -- so it
# gets its own, much looser cap. It exists to bound abuse, not to pace a
# typing student.
state_quota = quotas.Quota(cooldown=1, hourly=1200)

# The forum, counted PER ACCOUNT and not by IP: two students behind the same
# school NAT should not get in each other's way. It covers ONLY writes -- a
# quota that blocked rereading a thread would block following the reply one
# is waiting for.
forum_quota = quotas.Quota(config.FORUM_COOLDOWN, config.FORUM_HOURLY)

# The Console, counted PER ACCOUNT like the forum's and for the same reason:
# it is signed-in only, so an IP counter would put a whole school behind one
# tally. A session holds a container for minutes, where a submission holds one
# for seconds -- hence its own counter rather than a share of `quota_connecte`.
scratch_quota = quotas.Quota(config.SCRATCH_COOLDOWN, config.SCRATCH_HOURLY)

# The open-windows counter. No database, no account, no token.
presence = quotas.Presence()

# --- WebSocket close codes -----------------------------------------------------
# THEY LIVE HERE BECAUSE TWO ROUTERS USE THEM. `/team/live` declared them
# first; `/scratch/live` speaks the same dialect, so the page can tell "your
# session expired" from "you are not on a team" from "come back in a minute"
# with one table instead of two that drift. A test refuses a second
# declaration in a router.
CLOSE_UNAUTHORIZED = 4401
CLOSE_FORBIDDEN = 4403
CLOSE_BUSY = 4429
CLOSE_BAD = 4400
# NEUF, et propre à la Console : « le service ne répond pas », qui n'est ni un
# refus ni une erreur du client. C'est ce qu'on renvoie quand aucun worker ne
# réclame le job -- sans ça, une unité systemd arrêtée ressemble à un programme
# qui n'imprime rien.
CLOSE_UNAVAILABLE = 4503


class Refus(Exception):
    """An error response, carried by an exception.

    NOT `HTTPException`: that one can only carry a `detail`, while a 429 must
    also return `retry_after` -- the page uses it to say how long to wait
    instead of inviting a re-click. A dict in `detail` would produce
    `{"error": {...}}`, which the page does not know how to read.
    """

    def __init__(self, code, message, **extra):
        super().__init__(message)
        self.code = code
        self.message = message
        self.extra = extra


def utilisateur(request: Request) -> str:
    """The caller's `sub`, or 401/503.

    503 AND NOT 401 when sign-in is not configured: "there are no accounts
    here" and "your token expired" call for two different actions from the
    student, and the page distinguishes them.
    """
    if not security.oidc_enabled():
        raise Refus(503, "la persistance n'est pas configurée")
    sub = security.current_user(request.headers)
    if sub is None:
        raise Refus(401, "connexion requise ou expirée")
    return sub


def utilisateur_forum(request: Request) -> str:
    """Same, but the forum must be enabled -- and that is checked FIRST.

    Order matters: a deployment with no moderator answers 503 "discussions
    are not enabled" even with no token. Chaining onto `utilisateur` first
    would answer 401 to an anonymous visitor, which would suggest the forum
    exists and that signing in is all it takes.
    """
    if not forum_service.forum_enabled():
        raise Refus(503, "les discussions ne sont pas activées sur ce déploiement")
    return utilisateur(request)


def moderateur(request: Request) -> str:
    """A moderator's `sub`, or 403.

    THE ROLE IS RECOMPUTED HERE, ON EVERY CALL, FROM THE AUTHENTICATED `sub`.
    The page does receive a `moderateur` flag, but it only decides what to
    draw: no route takes it at face value.
    """
    sub = utilisateur_forum(request)
    if not security.is_moderator(sub):
        raise Refus(403, "réservé à l'enseignant")
    return sub


Sub = Annotated[str, Depends(utilisateur)]
SubForum = Annotated[str, Depends(utilisateur_forum)]
SubModerateur = Annotated[str, Depends(moderateur)]


def freiner_ecriture(request: Request) -> None:
    """The state-write throttle (draft, preferences), by IP."""
    qui = security.client_id(request.headers, pair_tcp(request))
    with verrou:
        attente = state_quota.check(qui, time.time())
    if attente:
        raise Refus(429, f"trop d'écritures -- réessaie dans {attente} s",
                    retry_after=attente)


def freiner_forum(sub: str) -> None:
    """The forum throttle, by ACCOUNT. Called after content validation.

    AFTER validation: a message refused for being empty must not consume
    anyone's quota.
    """
    with verrou:
        attente = forum_quota.check(sub, time.time())
    if attente:
        raise Refus(429, f"trop de messages d'un coup -- réessaie dans {attente} s",
                    retry_after=attente)


def pair_tcp(request: Request) -> str:
    """The TCP peer's address, or "" -- `request.client` is None under TestClient."""
    return request.client.host if request.client else ""
