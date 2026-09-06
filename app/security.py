"""Qui appelle : jetons OIDC, identité, rôle de modération, client de quota.

DEUX CHOSES DIFFÉRENTES VIVENT ICI, et il ne faut pas les confondre :

  * `current_user()` rend le `sub` d'un compte AUTHENTIFIÉ -- le jeton est validé
    en appelant `/userinfo` chez l'émetteur, jamais décodé sur parole. C'est la
    SEULE source d'identité de toute l'application : aucune route ne lit un
    identifiant d'utilisateur dans un corps de requête.
  * `client_id()` rend une étiquette pour compter les quotas. Elle est
    falsifiable si on tape l'origine sans passer par Cloudflare : c'est un
    régulateur de charge, PAS un contrôle d'accès. La clé de session est le
    contrôle d'accès.

`is_moderator()` est recalculé à chaque appel depuis le `sub` validé et la liste
de l'environnement, JAMAIS depuis un claim du jeton : un rôle dérivé d'un claim
non vérifié se réclame depuis n'importe quel compte.
"""

import hashlib
import json
import time
import urllib.parse
import urllib.request
from threading import Lock

import config
import state


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """urllib replays request headers on a redirect target.

    A student's bearer token would then be handed to whoever wrote the Location
    header. We never follow one.
    """

    def redirect_request(self, *args, **kwargs):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def _get_json(url, headers=None):
    """One JSON GET, bounded in time and in size. Raises on anything unexpected."""
    request = urllib.request.Request(url, headers=headers or {})
    with _OPENER.open(request, timeout=5) as response:
        raw = response.read(65536)
    return json.loads(raw)


def oidc_enabled():
    """True when signing in can be offered.

    All three are required: an issuer, a client id, and a database. Offering a
    login with nowhere to store the result would only disappoint. HTTPS is part
    of the test -- a bearer token over cleartext is a token given away.
    """
    return (config.OIDC_ISSUER.startswith("https://")
            and bool(config.OIDC_CLIENT_ID) and state.enabled())


_discovery = {"until": 0.0, "userinfo": ""}


def userinfo_url():
    """Rauthy's userinfo endpoint, read from its OIDC discovery document.

    Read rather than hardcoded: provider paths are not standardised, and a
    guessed URL breaks on the first upgrade.

    IT MUST LIVE UNDER THE CONFIGURED ISSUER. Without that check, anyone able to
    influence the discovery document -- a wrong environment variable is enough --
    would have our students' tokens delivered to a host of their choosing. This
    is an SSRF guard, and it is the reason this function exists at all.
    """
    now = time.time()
    if _discovery["until"] > now:
        return _discovery["userinfo"]
    url = ""
    try:
        document = _get_json(config.OIDC_ISSUER + "/.well-known/openid-configuration")
        candidate = document.get("userinfo_endpoint", "")
        if isinstance(candidate, str) and candidate.startswith(config.OIDC_ISSUER + "/"):
            url = candidate
    except Exception:
        url = ""
    # A failed discovery is cached briefly too: a provider that is down must not
    # turn every request into another call to it.
    _discovery.update(until=now + (600 if url else 30), userinfo=url)
    return url


# Token fingerprint -> (sub, preferred_username, expiry). THE KEY IS A SHA-256 OF THE TOKEN, not the
# token: this dict ends up in a core dump or a traceback sooner or later, and a
# raw access token found there would still be replayable.
_tokens = {}
_tokens_lock = Lock()
TOKENS_MAX = 500


def current_user(headers):
    """The `sub` behind the Authorization header, or None.

    VALIDATED BY ASKING RAUTHY (/userinfo) instead of verifying a signature
    locally: that keeps a crypto library and its key rotation out of an image
    that serves 27 students. The price is one round trip per cold token, paid
    down by a few minutes of cache.

    FAILURES ARE CACHED TOO, briefly. Without that, a loop of made-up tokens
    would turn this API into a request amplifier aimed at Rauthy.
    """
    header = headers.get("Authorization", "")
    if not header.startswith("Bearer ") or not oidc_enabled():
        return None
    token = header[7:].strip()
    if not token or len(token) > 4096:
        return None
    fingerprint = hashlib.sha256(token.encode()).hexdigest()
    now = time.time()
    with _tokens_lock:
        known = _tokens.get(fingerprint)
        if known and known[2] > now:
            return known[0]
    sub, nom = _ask_userinfo(token)
    with _tokens_lock:
        # ponytail: full flush rather than an LRU. The cache is a round-trip
        # saver, not a session store; losing it costs one call per student.
        if len(_tokens) >= TOKENS_MAX:
            _tokens.clear()
        _tokens[fingerprint] = (sub, nom, now + (config.OIDC_TTL if sub else 30))
    return sub


def current_name(headers):
    """Rauthy's `preferred_username` for this token, or "".

    A SUGGESTION, NOT AN IDENTITY. It only pre-fills the "Display name" field
    for an account that has not chosen one yet: nothing is stored, nothing is
    shown to others until the student has saved AND checked the box. Syncing
    it for real would publish someone's sign-in name into a class forum
    without them asking -- and at Rauthy, that name is often the school's
    access code.

    READS THE CACHE, CALLS NOTHING: `current_user` just filled it on the same
    request. An empty cache (or a `current_user` replaced by a test) returns
    "", and the field opens empty as before.
    """
    header = headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return ""
    fingerprint = hashlib.sha256(header[7:].strip().encode()).hexdigest()
    with _tokens_lock:
        known = _tokens.get(fingerprint)
    return known[1] if known and known[2] > time.time() and known[1] else ""


def _ask_userinfo(token):
    """(sub, preferred_username) -- (None, "") when the token is worthless.

    The second value is ONLY ever a name suggestion (see `current_name`), and
    it goes through the same validation a student's own typing would: a claim
    is no more trustworthy for coming from an identity provider.
    """
    url = userinfo_url()
    if not url:
        return None, ""
    try:
        claims = _get_json(url, {"Authorization": "Bearer " + token})
    except Exception:
        return None, ""
    sub = claims.get("sub") if isinstance(claims, dict) else None
    # This value becomes half of a primary key: bound it, and refuse anything
    # that is not a string. Rauthy issues a UUID, but we do not assume it.
    if not isinstance(sub, str) or not 0 < len(sub) <= 128:
        return None, ""
    # LOCAL IMPORT, TO BREAK A CYCLE: `services.forum` needs `is_moderator` and
    # `oidc_enabled` from here, and this one call needs its name validation.
    # The cycle is real, it is tiny, and resolving it by moving validation to
    # the caller would mean someone eventually forgets to validate. A claim is
    # no more trustworthy for coming from an identity provider.
    from services.forum import forum_pseudo

    propose = claims.get("preferred_username")
    nom, _ = forum_pseudo(propose if isinstance(propose, str) else None)
    return sub, nom or ""


def client_id(headers, peer, station=None):
    """Who counts as "one student" for quota purposes.

    CF-Connecting-IP first: Cloudflare always OVERWRITES it, so a client
    cannot forge it as long as it goes through Cloudflare. X-Forwarded-For
    gives no such guarantee (Cloudflare only APPENDS the client IP to a value
    the client controls); it exists only for direct access from the LAN.

    ponytail: falsifiable by hitting the origin without going through
    Cloudflare. This is a load regulator, not access control -- the session
    key is the access control.
    """
    # THE ACCOUNT FIRST, THE IP AS A FALLBACK. In the lab, 27 students exit
    # through a single NATed IP: counting by IP would make one student block
    # the whole room. A validated `sub` is fairer AND harder to forge than the
    # IP. The anonymous visitor only has their IP -- and no account to protect.
    sub = current_user(headers)
    if sub:
        return "u:" + sub[:62]
    cf = headers.get("CF-Connecting-IP")
    if cf:
        address = cf.strip()[:64]
    else:
        xff = headers.get("X-Forwarded-For")
        address = xff.split(",")[0].strip()[:64] if xff else peer
    # THE ANONYMOUS VISITOR IS COUNTED PER STATION, NOT PER ROOM. In the first
    # labs nobody is signed in yet: 27 stations exit through a single NATed
    # IP, and an IP-based counter makes all of them wait because of one. The
    # token comes from the browser (localStorage), so it proves nothing -- but
    # the IP alone proved nothing either once you hit the origin directly.
    #
    # THE IP STAYS IN THE KEY: a replayed token cannot borrow another
    # network's counter, and a station without a token falls back exactly to
    # the old behavior.
    #
    # ponytail: replayable by clearing one's localStorage. This is a load
    # regulator, and `QUEUE_MAX` already bounds the worst case; a per-IP cap
    # on top the day someone turns it into a game.
    if station:
        return (address + "/" + str(station))[:128]
    return address


def is_moderator(sub):
    """The role check, and it lives HERE -- never in the browser.

    The page does receive a `moderateur` flag, but it is a DISPLAY flag: every
    moderation route recomputes it from the authenticated `sub`. A boolean
    returned by a client is not an authorization.
    """
    return bool(sub) and sub in config.FORUM_MODERATORS
