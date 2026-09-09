"""ctester -- all the settings, in one place.

A deployment is steered by environment variables, and every value here
carries the Ansible role's default next to it: that is what makes the checks
runnable on the controller without installing or deploying anything.

IMPORT THE MODULE, NOT ITS NAMES: `import config` then `config.KEY`, never
`from config import KEY`. A `from ... import` freezes the value at import
time, and the tests set these constants afterward to exercise a deployment
different from the one running them. A frozen import makes those tests
silently inert -- they would pass while testing nothing.

STANDARD LIBRARY, NOT `pydantic-settings`: this is twenty `os.environ.get`
calls with a default. One more settings model here would only add one more
dependency in the sole process exposed to the Internet.
"""

import os
import re


def _entier(nom, defaut):
    """An integer from the environment, or the default if the value is not one.

    A bare `int()` would fail the container's STARTUP on a typo in a `.env`
    file -- a mistyped variable must degrade a setting, not make the service
    unreachable.
    """
    try:
        return int(os.environ.get(nom, defaut))
    except ValueError:
        return int(defaut)


# --- Filesystem --------------------------------------------------------------
SPOOL = os.environ.get("CTESTER_SPOOL", "/spool")
# THE PAGE LIVES ELSEWHERE THAN THE CATALOG since `web/` is published
# separately. TEMPORARY: exists only for the duration of the move to GitHub
# Pages.
#
# TO TURN THE PAGE OFF, EMPTY THE VARIABLE, DO NOT DELETE IT
# (`CTESTER_PAGE=` in Compose). Absent, the default below takes over and the
# router looks for `/web` in a container that no longer mounts it: a 500
# "missing file" on every visit instead of the expected 404. Empty -> the
# router is not mounted at all, and this origin answers only on data.
PAGE = os.environ.get("CTESTER_PAGE", "/web")

# THE PUBLISHED CONTENT, AND IT IS NOW THE CATALOG'S ONLY SOURCE. A
# `current.json` pointer and one directory per revision, written by
# `publish_content.py`. Empty -> `/catalog.json` answers 404 and no exercise
# resolves any more: since phase 8 there is no more `tps.json` fallback, so
# the rollback is to rewrite the pointer, never to empty the variable.
#
# THE POINTER IS RE-READ ON EVERY REQUEST, like everything else here:
# republishing must not require recreating the container.
PUBLISHED = os.environ.get("CTESTER_PUBLISHED", "")

# --- HTTP boundary -----------------------------------------------------------
# ORIGINS ALLOWED TO CALL THIS API, never `*`: every authenticated request
# carries an `Authorization` header, and `*` would open it to any page on the
# web. An origin absent from this list receives NO CORS header at all -- the
# browser then blocks on its own -- rather than a 403: a forgotten setting
# must not turn into an opaque server-side outage.
ORIGINS = tuple(o.strip().rstrip("/") for o in os.environ.get(
    "CTESTER_ORIGINS",
    "https://tch009.thevhome.com,https://vianpyro.github.io").split(",")
    if o.strip())

# TRANSITION: the origin the PAGE calls. This server still serves the page
# during the move, so its CSP must allow `connect-src` to the API -- otherwise
# the window where `tch009` is still on the Dell but `config.js` already
# points at `tch099` is a dead page. Disappears with the page's router.
API_ORIGIN = os.environ.get("CTESTER_API_ORIGIN", "https://tch099.thevhome.com")

PORT = _entier("CTESTER_PORT", "8000")

# THE TWO RENDERING LIBRARIES, PINNED IN THEIR FILE NAME. They live in the
# repo (`web/vendor/`, see its README) and are served from this origin: the
# CSP says `script-src 'self'`, so a CDN would be blocked, and that is
# intentional. Bumping a version requires touching this list AND `forum.js`
# -- an HTML sanitizer upgrade must not happen by accident.
VENDOR = ("vendor/marked-18.0.11.umd.js", "vendor/purify-3.4.14.min.js",
          # Yjs, and it is the collaboration itself rather than a rendering
          # helper: `team.js` fetches it the moment a team workspace opens,
          # never before. Same rules as the other two -- pinned in the file
          # name, served from this origin, and bumped in three places on
          # purpose (here, `web/vendor/README.md`, `team.js`).
          "vendor/yjs-13.6.32.iife.js")

# AUTOMATIC DOCUMENTATION IS OFF BY DEFAULT, and this is not modesty.
# `/docs`, `/redoc` and `/openapi.json` are public in FastAPI: they describe
# every route, every field and every bound of an API sitting on personal
# infrastructure. Useful in development, handed to a stranger in production.
DOCS = os.environ.get("CTESTER_DOCS", "") == "1"

# --- Submissions --------------------------------------------------------------
KEY = os.environ.get("CTESTER_KEY", "")
COOLDOWN = _entier("CTESTER_COOLDOWN", "15")
# SIGNED IN MEANS LESS WAITING, and it is not a favor: an account is a fair
# quota label (see `client_id`), where the anonymous visitor is counted by a
# declared station, so more easily replayed. The tighter window pays for that
# uncertainty; it opens no extra door, the hourly cap is the same.
COOLDOWN_CONNECTE = _entier("CTESTER_COOLDOWN_CONNECTE", "8")
HOURLY = _entier("CTESTER_HOURLY_QUOTA", "40")
QUEUE_MAX = _entier("CTESTER_QUEUE_MAX", "60")
# ONLY EVER USED TO DIVIDE THE ANNOUNCED ETA, never to launch anything: the
# workers are host systemd units, this container cannot see them. Must match
# the Ansible role's `ctester_workers` (2) -- set too high, the page promises
# a verdict faster than the service can deliver.
WORKERS = _entier("CTESTER_WORKERS", "2")
MAX_CODE = _entier("CTESTER_MAX_CODE_BYTES", "65536")

# --- Accounts (optional) ------------------------------------------------------
# SIGNING IN IS OPTIONAL, AND EVERYTHING MUST HOLD WITHOUT IT. Without an
# OIDC issuer or a database, `/oidc.json` answers `{}`, the page does not even
# show the button, and the anonymous path is exactly what it was. This is the
# non-regression bar for this whole feature.
OIDC_ISSUER = os.environ.get("CTESTER_OIDC_ISSUER", "").rstrip("/")
OIDC_CLIENT_ID = os.environ.get("CTESTER_OIDC_CLIENT_ID", "")
OIDC_TTL = _entier("CTESTER_OIDC_CACHE_TTL", "300")

# --- Peer help forum -----------------------------------------------------------
# OFF BY DEFAULT, AND THAT IS THE SAFE SETTING. Without at least one
# configured moderator `sub`, the forum is off: the button does not appear,
# `forum.js` is never requested, and the routes answer 503 saying so. A forum
# with nobody to moderate it is a solution-sharing channel with a charter on
# top -- we do not open it "in the meantime".
#
# OPAQUE OIDC `sub`s, comma- or space-separated, NEVER a token claim: a role
# derived from an unverified claim can be claimed from any account.
FORUM_MODERATORS = frozenset(
    s for s in re.split(r"[,\s]+",
                        os.environ.get("CTESTER_FORUM_MODERATORS", "")) if s)
FORUM_MAX_CHARS = _entier("CTESTER_FORUM_MAX_CHARS", "1200")
FORUM_COOLDOWN = _entier("CTESTER_FORUM_COOLDOWN", "10")
FORUM_HOURLY = _entier("CTESTER_FORUM_HOURLY_QUOTA", "20")
FORUM_PSEUDO_MAX = _entier("CTESTER_FORUM_PSEUDO_MAX", "24")
# READ bound for a thread and the moderation queue. An exercise thread at 27
# students does not come close; the bound exists so the page can never
# receive an endless object the day something goes wrong.
FORUM_MAX_FIL = 200

# --- Le chat en direct ---------------------------------------------------------
# LA SOCKET EST UNE SONNETTE, PAS UN TRANSPORT. Une trame dit « du neuf » et
# le client relance `GET /forum` : le quota, la borne de texte, les listes
# fermées et le tirage d'alias restent donc sur la route HTTP, à un seul
# endroit. Relayer le texte voudrait dire réimplémenter tout ça par
# destinataire, sur le chemin le plus difficile à éprouver.
#
# LE PLAFOND EST PAR SALLE, et une salle est un fil. Il existe pour qu'un fil
# ne puisse pas immobiliser le processus, pas pour rationner : 60 laisse
# passer une cohorte entière sur le même exercice.
FORUM_LIVE_MAX = _entier("CTESTER_FORUM_LIVE_MAX", "60")
# Une trame entrante est JETÉE (le client n'a rien à dire, il écrit en HTTP) ;
# la borne est là parce qu'une trame WebSocket ne passe pas par le middleware,
# et qu'aucune porte de cette application ne doit rester non bornée.
FORUM_LIVE_FRAME = _entier("CTESTER_FORUM_LIVE_FRAME", "4096")
# Combien de résultats une recherche rend. Elle sert AUSSI de détection de
# doublon pendant la frappe, d'où la petitesse : trois propositions se lisent,
# vingt se sautent.
FORUM_SEARCH_MAX = _entier("CTESTER_FORUM_SEARCH_MAX", "5")

# ponytail: a session's list of groups lives here, edited like the policy.
# Empty => free-text field 1..99 (the old behavior). The column stays
# `SMALLINT CHECK (1..99)`: a session's list does not live in the schema. A
# non-numeric value is ignored rather than killing startup.
FORUM_GROUPES = tuple(
    int(x) for x in
    os.environ.get("CTESTER_FORUM_GROUPES", "4,6").replace(",", " ").split()
    if x.lstrip("-").isdigit())

# --- Le pont Discord -----------------------------------------------------------
# LE COURS A DÉJÀ UN DISCORD, ET C'EST LÀ QUE LA COHORTE EST. Un chat vide
# reste vide : ce n'est pas un problème d'interface mais de masse critique.
# Le pont relaie donc les deux sens -- mais SEULEMENT le chat public.
#
# CE QUI NE SORT JAMAIS : une question privée, un `sub`, un code d'étudiant.
# `discord.annoncer()` refuse tout fil qui n'est pas `est_chat()`, et c'est
# le seul `if` que la propriété coûte. `D-013` le dit et révise `D-008`.
#
# LES TROIS SONT VIDES PAR DÉFAUT, comme `FORUM_MODERATORS` : sans elles le
# pont n'existe pas, la route entrante n'est pas montée, et rien ne part.
DISCORD_WEBHOOK = os.environ.get("CTESTER_DISCORD_WEBHOOK", "").strip()
# La clé du pont entrant. Vide => la route N'EST PAS MONTÉE, même dessin que
# `DOCS` : il n'y a rien à contourner quand il n'y a rien.
DISCORD_BRIDGE_KEY = os.environ.get("CTESTER_DISCORD_BRIDGE_KEY", "").strip()
# L'invitation, affichée dans le chat. Purement cosmétique, et c'est le repli
# quand le pont est éteint : les deux endroits existent, autant le dire.
DISCORD_URL = os.environ.get("CTESTER_DISCORD_URL", "").strip()
# Combien de secondes on attend Discord. Court exprès : c'est un fil démon,
# personne ne l'attend, et un webhook lent ne doit pas retenir un descripteur.
DISCORD_TIMEOUT = _entier("CTESTER_DISCORD_TIMEOUT", "5")
# LE PRÉFIXE D'UN COMPTE VENU DE DISCORD. Même propriété que `@chat:` : `@`
# ne peut apparaître dans aucun identifiant de catalogue, donc un compte de
# pont ne résout chez personne et ne devient jamais un chemin.
DISCORD_ACCOUNT_PREFIX = "@discord:"

# --- Team assignments -----------------------------------------------------------
# NOTHING TURNS THIS FEATURE ON OR OFF, and that is deliberate: it is the
# CONTENT that opts in (an assignment file with a `team` block) and the ROSTER
# that decides who sees it. A deployment with no assignment and no roster
# behaves exactly as it did -- there is no flag to forget in a third place.

# HOW OFTEN A REVISION IS WORTH KEEPING, per author and per document. Every
# keystroke would be one Postgres row per keystroke; two minutes is short
# enough to answer "who wrote this" and long enough that an afternoon of work
# is a readable list rather than a log. See `state.write_team_document`.
TEAM_REVISION_WINDOW = _entier("CTESTER_TEAM_REVISION_WINDOW", "120")
# The READ bound on a history. A term of four people editing six exercises
# does not come close; the bound exists so the page can never receive an
# endless object the day something goes wrong.
TEAM_REVISIONS_MAX = _entier("CTESTER_TEAM_REVISIONS_MAX", "200")
# Sockets accepted in one room. A team is three or four; the margin covers
# someone with two tabs open, and the cap is what stops one account from
# opening a thousand.
TEAM_LIVE_MAX = _entier("CTESTER_TEAM_LIVE_MAX", "12")
# The biggest collaboration frame relayed, in bytes. A CRDT update for a
# keystroke is a few dozen bytes; a whole-document sync is bounded by
# MAX_CODE, and base64 costs a third more.
TEAM_LIVE_MAX_FRAME = _entier("CTESTER_TEAM_LIVE_MAX_FRAME",
                              str(MAX_CODE * 2))

# --- Presence ------------------------------------------------------------------
PRESENCE_TTL = _entier("CTESTER_PRESENCE_TTL", "150")

# --- La Console ----------------------------------------------------------------
# UN TERMINAL C INTERACTIF, ÉTEINT PAR L'ABSENCE D'UNE VARIABLE -- comme le
# forum, et pour la même raison : « personne ne clique dessus » et « ça n'existe
# pas » se ressemblent trop vus de l'extérieur pour laisser quelqu'un deviner
# lequel des deux c'est. Vide -> le bouton n'apparaît pas, `/oidc.json` annonce
# `scratch: false`, et la socket refuse en le disant.
#
# LES PLAFONDS DU CONTENEUR NE SONT PAS ICI, ET C'EST DÉLIBÉRÉ. Le mur, le temps
# CPU, la mémoire et les octets de sortie appartiennent au worker, qui est le
# seul à posséder un conteneur et des cœurs ; ce processus-ci n'a que l'identité
# et la frontière HTTP. Chaque plafond vit là où vit la seule information
# capable de l'appliquer, et nulle part deux fois. Le TTL affiché à la page vient
# du worker, dans `state.json` : elle décompte un nombre qu'on lui a dit, pas une
# constante qu'elle configure.
SCRATCH = os.environ.get("CTESTER_SCRATCH", "") == "1"
# Sessions par heure et par compte, et secondes entre deux. COMPTÉ PAR COMPTE et
# pas par IP, contrairement aux soumissions : la Console est réservée aux comptes
# connectés, et un quota par IP mettrait toute une école derrière un compteur.
SCRATCH_HOURLY = _entier("CTESTER_SCRATCH_HOURLY_QUOTA", "20")
SCRATCH_COOLDOWN = _entier("CTESTER_SCRATCH_COOLDOWN", "10")
# La plus grosse trame d'entrée acceptée, en octets. Une ligne tapée fait
# quelques octets ; ce plafond existe pour qu'un client qui ignore l'interface ne
# puisse pas pousser un fichier entier par la socket.
SCRATCH_FRAME = _entier("CTESTER_SCRATCH_FRAME", "4096")
# Ce qu'une session entière a le droit d'accumuler sur l'entrée standard.
SCRATCH_IN_MAX = _entier("CTESTER_SCRATCH_IN_MAX", "65536")
# Combien de temps on attend que le worker réclame le job avant de dire que
# personne ne répond. SANS CE DÉLAI, une unité systemd arrêtée ressemble à un
# programme qui n'imprime rien -- exactement la forme de panne que la case
# « Websockets Support » de NPM a déjà produite pour /team/live.
SCRATCH_START_TIMEOUT = _entier("CTESTER_SCRATCH_START_TIMEOUT", "20")
