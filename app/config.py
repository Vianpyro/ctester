import os
import re


def _int(name, default):
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return int(default)


SPOOL = os.environ.get("CTESTER_SPOOL", "/spool")
# Set to "" to disable the page router; leaving it unset falls back to /web.
PAGE = os.environ.get("CTESTER_PAGE", "/web")

PUBLISHED = os.environ.get("CTESTER_PUBLISHED", "")

ORIGINS = tuple(o.strip().rstrip("/") for o in os.environ.get(
    "CTESTER_ORIGINS",
    "https://tch009.thevhome.com,https://vianpyro.github.io").split(",")
    if o.strip())

API_ORIGIN = os.environ.get("CTESTER_API_ORIGIN", "https://tch099.thevhome.com")

PORT = _int("CTESTER_PORT", "8000")
DOCS = os.environ.get("CTESTER_DOCS", "") == "1"

KEY = os.environ.get("CTESTER_KEY", "")
COOLDOWN = _int("CTESTER_COOLDOWN", "15")
COOLDOWN_SIGNED_IN = _int("CTESTER_COOLDOWN_CONNECTE", "8")
HOURLY = _int("CTESTER_HOURLY_QUOTA", "40")
QUEUE_MAX = _int("CTESTER_QUEUE_MAX", "60")
# Only divides the announced ETA; must match the number of runner units on the host.
WORKERS = _int("CTESTER_WORKERS", "2")
MAX_CODE = _int("CTESTER_MAX_CODE_BYTES", "65536")

OIDC_ISSUER = os.environ.get("CTESTER_OIDC_ISSUER", "").rstrip("/")
OIDC_CLIENT_ID = os.environ.get("CTESTER_OIDC_CLIENT_ID", "")
OIDC_TTL = _int("CTESTER_OIDC_CACHE_TTL", "300")

FORUM_MODERATORS = frozenset(
    s for s in re.split(r"[,\s]+",
                        os.environ.get("CTESTER_FORUM_MODERATORS", "")) if s)
FORUM_MAX_CHARS = _int("CTESTER_FORUM_MAX_CHARS", "1200")
FORUM_COOLDOWN = _int("CTESTER_FORUM_COOLDOWN", "10")
FORUM_HOURLY = _int("CTESTER_FORUM_HOURLY_QUOTA", "20")
FORUM_PSEUDO_MAX = _int("CTESTER_FORUM_PSEUDO_MAX", "24")
FORUM_MAX_THREAD = 200

FORUM_LIVE_MAX = _int("CTESTER_FORUM_LIVE_MAX", "60")
FORUM_LIVE_FRAME = _int("CTESTER_FORUM_LIVE_FRAME", "4096")
FORUM_SEARCH_MAX = _int("CTESTER_FORUM_SEARCH_MAX", "5")

FORUM_GROUPS = tuple(
    int(x) for x in
    os.environ.get("CTESTER_FORUM_GROUPES", "4,6").replace(",", " ").split()
    if x.lstrip("-").isdigit())

DISCORD_WEBHOOK = os.environ.get("CTESTER_DISCORD_WEBHOOK", "").strip()
DISCORD_BRIDGE_KEY = os.environ.get("CTESTER_DISCORD_BRIDGE_KEY", "").strip()
DISCORD_URL = os.environ.get("CTESTER_DISCORD_URL", "").strip()
DISCORD_TIMEOUT = _int("CTESTER_DISCORD_TIMEOUT", "5")
DISCORD_ACCOUNT_PREFIX = "@discord:"

TEAM_REVISION_WINDOW = _int("CTESTER_TEAM_REVISION_WINDOW", "120")
TEAM_REVISIONS_MAX = _int("CTESTER_TEAM_REVISIONS_MAX", "200")
TEAM_LIVE_MAX = _int("CTESTER_TEAM_LIVE_MAX", "12")
TEAM_LIVE_MAX_FRAME = _int("CTESTER_TEAM_LIVE_MAX_FRAME",
                           str(MAX_CODE * 2))

PRESENCE_TTL = _int("CTESTER_PRESENCE_TTL", "150")

SCRATCH = os.environ.get("CTESTER_SCRATCH", "") == "1"
SCRATCH_HOURLY = _int("CTESTER_SCRATCH_HOURLY_QUOTA", "20")
SCRATCH_COOLDOWN = _int("CTESTER_SCRATCH_COOLDOWN", "10")
SCRATCH_FRAME = _int("CTESTER_SCRATCH_FRAME", "4096")
SCRATCH_IN_MAX = _int("CTESTER_SCRATCH_IN_MAX", "65536")
SCRATCH_START_TIMEOUT = _int("CTESTER_SCRATCH_START_TIMEOUT", "20")
