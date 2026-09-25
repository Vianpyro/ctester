import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from threading import Lock

import config
import log
import state


# Requests carry a bearer token, which must never follow a redirect elsewhere.
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def _get_json(url, headers=None):
    request = urllib.request.Request(url, headers=headers or {})
    with _OPENER.open(request, timeout=5) as response:
        raw = response.read(65536)
    return json.loads(raw)


def oidc_enabled():
    return (config.OIDC_ISSUER.startswith("https://")
            and bool(config.OIDC_CLIENT_ID) and state.enabled())


_discovery = {"until": 0.0, "userinfo": ""}


def userinfo_url():
    now = time.time()
    if _discovery["until"] > now:
        return _discovery["userinfo"]
    url = ""
    try:
        document = _get_json(config.OIDC_ISSUER + "/.well-known/openid-configuration")
        candidate = document.get("userinfo_endpoint", "")
        if isinstance(candidate, str) and candidate.startswith(config.OIDC_ISSUER + "/"):
            url = candidate
    except Exception as failure:
        _provider_down(failure)
    else:
        if url:
            _provider_up()
        else:
            _provider_down(None)
    _discovery.update(until=now + (600 if url else 30), userinfo=url)
    return url


# Logged on the transition only, like state.py's database outage.
_provider = {"down": False}


def _provider_down(failure):
    if _provider["down"]:
        return
    _provider["down"] = True
    log.event("oidc.unavailable", log.WARN,
              "the identity provider cannot be asked, signed-in requests answer auth_unavailable",
              {"server.address": urllib.parse.urlsplit(config.OIDC_ISSUER).hostname,
               "error.type": "no_userinfo_endpoint" if failure is None else None,
               "http.response.status_code": getattr(failure, "code", None)}, exc=failure)


def _provider_up():
    if _provider["down"]:
        _provider["down"] = False
        log.event("oidc.restored", log.INFO, "the identity provider answers again",
                  {"server.address": urllib.parse.urlsplit(config.OIDC_ISSUER).hostname})


class AuthUnavailable(Exception):
    """The provider could not be asked: the token may be valid, so this is not a 401."""


_tokens = {}
_tokens_lock = Lock()
TOKENS_MAX = 500


def current_user(headers, strict=False):
    """With strict, an unreachable provider raises AuthUnavailable instead of reading as anonymous."""
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
        if known and known[3] > now:
            return known[0]
    try:
        sub, name, moderator = _ask_userinfo(token)
    except AuthUnavailable:
        # Not cached: the token may be valid as soon as the provider answers again.
        if strict:
            raise
        return None
    with _tokens_lock:
        # Clearing everything is fine: the cache only saves userinfo round trips.
        if len(_tokens) >= TOKENS_MAX:
            _tokens.clear()
        _tokens[fingerprint] = (sub, name, moderator, now + (config.OIDC_TTL if sub else 30))
    if sub and RECORD_ROLES:
        _record_role(sub, moderator)
    return sub


def _known_token(headers):
    header = headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return None
    fingerprint = hashlib.sha256(header[7:].strip().encode()).hexdigest()
    with _tokens_lock:
        known = _tokens.get(fingerprint)
    return known if known and known[3] > time.time() else None


def current_name(headers):
    known = _known_token(headers)
    return known[1] if known and known[1] else ""


def holder_is_moderator(headers):
    known = _known_token(headers)
    return bool(known and known[0] and known[2])


def _ask_userinfo(token):
    url = userinfo_url()
    if not url:
        raise AuthUnavailable()
    try:
        claims = _get_json(url, {"Authorization": "Bearer " + token})
    except urllib.error.HTTPError as refused:
        if refused.code in (400, 401, 403):
            _provider_up()
            return None, "", False
        _provider_down(refused)
        raise AuthUnavailable() from refused
    except Exception as failure:
        _provider_down(failure)
        raise AuthUnavailable() from failure
    _provider_up()
    sub = claims.get("sub") if isinstance(claims, dict) else None
    if not isinstance(sub, str) or not 0 < len(sub) <= 128:
        return None, "", False
    from services.forum import forum_display_name

    propose = claims.get("preferred_username")
    name, _ = forum_display_name(propose if isinstance(propose, str) else None)
    groups = claims.get("groups")
    moderator = (bool(config.MODERATOR_GROUP) and isinstance(groups, list)
                 and config.MODERATOR_GROUP in groups)
    return sub, name or "", moderator


def client_id(headers, peer, station=None):
    """Rate-limit key, not an identity: forwarded headers are spoofable off Cloudflare."""
    sub = current_user(headers)
    if sub:
        return "u:" + sub[:62]
    cf = headers.get("CF-Connecting-IP")
    if cf:
        address = cf.strip()[:64]
    else:
        xff = headers.get("X-Forwarded-For")
        address = xff.split(",")[0].strip()[:64] if xff else peer
    if station:
        return (address + "/" + str(station))[:128]
    return address


def station_tag(station):
    """A short, stable pseudonym for an anonymous browser's random station id, so the
    admin can tell anonymous submitters apart without storing the id itself."""
    if not isinstance(station, str) or not station:
        return None
    return hashlib.sha256(("station:" + station[:64]).encode()).hexdigest()[:8]


def is_moderator(sub):
    return bool(sub) and sub in moderators()


RECORD_ROLES = True
_roster = {"stamp": None, "subs": frozenset()}
_roster_lock = Lock()
_record_lock = Lock()


def moderators():
    if not config.MODERATOR_GROUP:
        return frozenset()
    try:
        stat = os.stat(config.MODERATORS_FILE)
        stamp = (stat.st_mtime_ns, stat.st_size, stat.st_ino)
    except OSError:
        stamp = None
    with _roster_lock:
        if stamp != _roster["stamp"]:
            _roster.update(stamp=stamp, subs=_read_roster() if stamp else frozenset())
        return _roster["subs"]


def _read_roster():
    try:
        with open(config.MODERATORS_FILE, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return frozenset()
    if not isinstance(data, list):
        return frozenset()
    return frozenset(s for s in data if isinstance(s, str))


def _record_role(sub, moderator):
    with _record_lock:
        known = moderators()
        if (sub in known) == moderator:
            return
        subs = known | {sub} if moderator else known - {sub}
        temporary = config.MODERATORS_FILE + ".tmp"
        try:
            with open(temporary, "w", encoding="utf-8") as fh:
                json.dump(sorted(subs), fh)
            os.replace(temporary, config.MODERATORS_FILE)
        except OSError as failure:
            log.event("moderators.unwritable", log.ERROR,
                      "the moderator roster cannot be written, roles stay as they were",
                      {}, exc=failure)
            return
    log.event("moderators.changed", log.INFO,
              "an account joined the moderators" if moderator
              else "an account left the moderators", {})
