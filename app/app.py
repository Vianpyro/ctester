#!/usr/bin/env python3
"""ctester -- l'API du juge C. Fichier géré par Ansible : éditer le rôle.

Ce processus ne compile RIEN et n'exécute RIEN. Il valide une soumission,
l'écrit dans le spool, et lit le verdict qu'un worker de l'hôte y dépose. Il
n'a ni le socket Docker, ni accès au répertoire des tests -- c'est toute la
raison pour laquelle il peut être exposé à Internet.

Bibliothèque standard uniquement : rien à installer au démarrage, rien à
patcher, et l'image officielle python:3.13-slim suffit telle quelle.
"""

import hashlib
import hmac
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock

import etat

SPOOL = os.environ.get("CTESTER_SPOOL", "/spool")
STATIC = os.environ.get("CTESTER_STATIC", "/app")
KEY = os.environ.get("CTESTER_KEY", "")
COOLDOWN = int(os.environ.get("CTESTER_COOLDOWN", "15"))
HOURLY = int(os.environ.get("CTESTER_HOURLY_QUOTA", "40"))
QUEUE_MAX = int(os.environ.get("CTESTER_QUEUE_MAX", "60"))
MAX_CODE = int(os.environ.get("CTESTER_MAX_CODE_BYTES", "65536"))
PORT = int(os.environ.get("CTESTER_PORT", "8000"))

# SIGNING IN IS OPTIONAL, AND EVERYTHING BELOW MUST HOLD WITHOUT IT. With no
# OIDC issuer or no database, /oidc.json answers {}, the page does not even show
# the button, and the anonymous path is exactly what it was. That is the
# no-regression bar for this whole feature.
OIDC_ISSUER = os.environ.get("CTESTER_OIDC_ISSUER", "").rstrip("/")
OIDC_CLIENT_ID = os.environ.get("CTESTER_OIDC_CLIENT_ID", "")
OIDC_TTL = int(os.environ.get("CTESTER_OIDC_CACHE_TTL", "300"))

TP_RE = re.compile(r"\A[a-z0-9_-]{1,32}\Z")
JOB_RE = re.compile(r"\A[0-9a-f]{32}\Z")


def load_tps():
    """Les TP disponibles : [{id, mode, label}], publiés par le worker.

    Le web connaît le NOM, le MODE et le LIBELLÉ d'un TP, jamais son contenu --
    le répertoire des tests n'est pas monté dans ce conteneur, et le corrigé
    d'un quiz est retiré avant publication (publish_catalogue dans runner.py).
    """
    try:
        with open(os.path.join(STATIC, "tps.json"), encoding="utf-8") as fh:
            entries = json.load(fh)
        return [e for e in entries if isinstance(e, dict) and "id" in e]
    except (OSError, ValueError):
        return []


def find_tp(tp):
    """L'entrée de catalogue de ce TP, ou None. La seule porte vers un TP.

    Tout ce qui suit -- le mode, le nom de fichier écrit dans le spool, le
    chemin d'un quiz servi -- part d'ici. Un TP absent du catalogue n'existe pas,
    quel que soit le contenu du disque.
    """
    if not TP_RE.match(tp):
        return None
    for entry in load_tps():
        if entry["id"] == tp:
            return entry
    return None


def validate_files(entry, sent):
    """(files, message, status) -- THE SAME WHITELIST for a submission and a draft.

    File names come from the catalogue, never from the request. From lab 5 on, a
    submission is a module whose names the assignment imposes (calendrier.h,
    calendrier.c): a name that is not on the list is refused rather than dropped
    silently -- a student must know their file was not taken.

    Emptiness is NOT checked here: an empty submission is an error, an emptied
    draft is a legitimate thing to store. The caller decides.
    """
    if not isinstance(sent, dict):
        return None, "fichiers manquants", 400
    declared = [f["name"] for f in entry.get("files") or []] or ["submission.c"]
    unknown = sorted(k for k in sent if k not in declared)
    if unknown:
        return None, "fichier inattendu : " + ", ".join(unknown[:3]), 400
    files = {n: str(sent.get(n, "")) for n in declared}
    if len(json.dumps(files).encode()) > MAX_CODE:
        return None, f"soumission > {MAX_CODE // 1024} Ko", 413
    return files, None, 200


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
    return (OIDC_ISSUER.startswith("https://")
            and bool(OIDC_CLIENT_ID) and etat.enabled())


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
        document = _get_json(OIDC_ISSUER + "/.well-known/openid-configuration")
        candidate = document.get("userinfo_endpoint", "")
        if isinstance(candidate, str) and candidate.startswith(OIDC_ISSUER + "/"):
            url = candidate
    except Exception:
        url = ""
    # A failed discovery is cached briefly too: a provider that is down must not
    # turn every request into another call to it.
    _discovery.update(until=now + (600 if url else 30), userinfo=url)
    return url


# Token fingerprint -> (sub, expiry). THE KEY IS A SHA-256 OF THE TOKEN, not the
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
        if known and known[1] > now:
            return known[0]
    sub = _ask_userinfo(token)
    with _tokens_lock:
        # ponytail: full flush rather than an LRU. The cache is a round-trip
        # saver, not a session store; losing it costs one call per student.
        if len(_tokens) >= TOKENS_MAX:
            _tokens.clear()
        _tokens[fingerprint] = (sub, now + (OIDC_TTL if sub else 30))
    return sub


def _ask_userinfo(token):
    url = userinfo_url()
    if not url:
        return None
    try:
        claims = _get_json(url, {"Authorization": "Bearer " + token})
    except Exception:
        return None
    sub = claims.get("sub") if isinstance(claims, dict) else None
    # This value becomes half of a primary key: bound it, and refuse anything
    # that is not a string. Rauthy issues a UUID, but we do not assume it.
    if not isinstance(sub, str) or not 0 < len(sub) <= 128:
        return None
    return sub


def client_id(headers, peer):
    """Qui compte comme « un étudiant » pour les quotas.

    CF-Connecting-IP d'abord : Cloudflare l'ÉCRASE toujours, donc un client ne
    peut pas le forger tant qu'il passe par Cloudflare. X-Forwarded-For ne donne
    pas cette garantie (Cloudflare y AJOUTE l'IP client à une valeur que le
    client contrôle), il n'est là que pour un accès direct depuis le LAN.

    ponytail: falsifiable en tapant l'origine sans passer par Cloudflare. C'est
    un régulateur de charge, pas un contrôle d'accès -- la clé de session est le
    contrôle d'accès.
    """
    cf = headers.get("CF-Connecting-IP")
    if cf:
        return cf.strip()[:64]
    xff = headers.get("X-Forwarded-For")
    if xff:
        return xff.split(",")[0].strip()[:64]
    return peer


class Quota:
    """Fenêtre glissante en mémoire : {client: [horodatages]}.

    ponytail: remise à zéro au redémarrage du conteneur, et un étudiant qui
    change de réseau repart à neuf. Les deux sont acceptables pour un régulateur
    de charge. Persister le jour où quelqu'un en fait un jeu.
    """

    def __init__(self, cooldown, hourly):
        self.cooldown = cooldown
        self.hourly = hourly
        self.seen = {}

    def check(self, who, now):
        """Retourne le nombre de secondes à attendre, ou 0 si la soumission passe.

        Enregistre le passage UNIQUEMENT si elle passe : un étudiant qui se
        heurte au cooldown ne doit pas le rallonger en réessayant.
        """
        hits = [t for t in self.seen.get(who, ()) if t > now - 3600]
        if hits and now - hits[-1] < self.cooldown:
            return int(self.cooldown - (now - hits[-1])) + 1
        if len(hits) >= self.hourly:
            return int(3600 - (now - hits[0])) + 1
        hits.append(now)
        self.seen[who] = hits
        if len(self.seen) > 5000:
            self.seen = {
                k: v for k, v in self.seen.items() if v and v[-1] > now - 3600
            }
        return 0


def scan_jobs():
    """(job_id, horodatage, terminé) pour chaque job du spool.

    L'horodatage vient du mtime de job.json, que le worker ne touche jamais --
    donc l'ordre vu ici est celui que le worker consomme, et le rang affiché à
    l'étudiant est vrai.
    """
    jobs = []
    try:
        entries = list(os.scandir(SPOOL))
    except OSError:
        return jobs
    for entry in entries:
        if not entry.is_dir():
            continue
        try:
            stamp = os.stat(os.path.join(entry.path, "job.json")).st_mtime
        except OSError:
            continue  # répertoire en cours d'écriture : pas encore un job
        done = os.path.exists(os.path.join(entry.path, "result.json"))
        jobs.append((entry.name, stamp, done))
    return jobs


def queue_position(jobs, job_id):
    """Rang 1-based du job parmi ceux qui attendent encore. 0 s'il n'attend plus."""
    pending = sorted((stamp, name) for name, stamp, done in jobs if not done)
    for rank, (_, name) in enumerate(pending, 1):
        if name == job_id:
            return rank
    return 0


class Handler(BaseHTTPRequestHandler):
    server_version = "ctester"
    quota = Quota(COOLDOWN, HOURLY)
    # Draft and state writes are cheap -- no compiler, no container -- so they
    # get their own, far looser limiter. It exists to bound abuse, not to pace
    # a student who types.
    state_quota = Quota(cooldown=1, hourly=1200)
    lock = Lock()

    # HTTP/1.1 pour garder la connexion ouverte pendant le sondage : à 40
    # étudiants qui interrogent /r/<id> toutes les 2 s, une poignée de main TCP
    # par requête est du gaspillage pur. Chaque réponse d'ici pose un
    # Content-Length, ce que le keep-alive exige.
    protocol_version = "HTTP/1.1"

    def log_request(self, *args):
        """Silence sur le chemin heureux.

        Le sondage produit des centaines de 200 par TP, qui noieraient tout ce
        qui est intéressant. `log_request` seulement, pas `log_message` : les
        erreurs passent par `log_error` et doivent continuer d'apparaître dans
        `docker logs`.
        """

    def _json(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _file(self, name, ctype):
        try:
            with open(os.path.join(STATIC, name), "rb") as fh:
                body = fh.read()
        except OSError:
            self._json(500, {"error": "fichier manquant"})
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        # no-store sur la page elle-même : sans en-tête, un navigateur la met en
        # cache heuristiquement, et un correctif déployé ne se voit pas -- on
        # déboguerait alors une version qui n'est plus sur le serveur. Le fichier
        # fait quelques kilooctets et est lu depuis un bind mount ; le recharger
        # à chaque visite ne coûte rien.
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_HEAD(self):  # noqa: N802 -- imposé par BaseHTTPRequestHandler
        path = self.path.split("?", 1)[0]

        if path == "/healthz":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", "12")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()

        elif path in ("/", "/index.html"):
            try:
                size = os.path.getsize(os.path.join(STATIC, "index.html"))
            except OSError:
                self.send_response(500)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return

            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(size))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()

        else:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()

    def do_GET(self):  # noqa: N802 -- imposé par BaseHTTPRequestHandler
        path = self.path.split("?", 1)[0]
        # Liste blanche explicite, PAS SimpleHTTPRequestHandler : ce processus
        # ne doit jamais pouvoir servir un fichier arbitraire de son système de
        # fichiers, quelle que soit la créativité du chemin demandé.
        if path == "/healthz":
            self._json(200, {"ok": True})
        elif path in ("/", "/index.html"):
            self._file("index.html", "text/html; charset=utf-8")
        elif path == "/tps.json":
            # RELU À CHAQUE FOIS, pas mis en cache au démarrage : publier un
            # nouveau TP est alors `--tags tests` et rien d'autre. Une valeur
            # en cache voudrait dire recréer le conteneur pour ajouter une
            # ligne à un menu déroulant, et c'est le genre d'étape qu'on oublie
            # le soir où on ajoute le TP4.
            self._json(200, load_tps())
        elif path.startswith("/quiz/") and path.endswith(".json"):
            self._quiz(path[6:-5])
        elif path.startswith("/r/"):
            self._result(path[3:])
        elif path == "/oidc.json":
            # The page asks this before showing anything: an empty object means
            # "no sign-in here", and it then behaves exactly as it always did.
            self._json(200, {"issuer": OIDC_ISSUER, "client_id": OIDC_CLIENT_ID}
                            if oidc_enabled() else {})
        elif path == "/etats":
            self._states()
        elif path == "/brouillon":
            self._read_draft()
        else:
            self._json(404, {"error": "inconnu"})

    # --- Signed-in students -------------------------------------------------
    # Every route below needs a token, and NONE of them takes a user identifier
    # from the request. `qui()` is the only source of `utilisateur`; that is
    # what stops one student from writing into another's state.

    def _who(self):
        """The caller's `sub`, or None after answering 401/503 itself."""
        if not oidc_enabled():
            self._json(503, {"error": "la persistance n'est pas configurée"})
            return None
        sub = current_user(self.headers)
        if sub is None:
            self._json(401, {"error": "connexion requise ou expirée"})
        return sub

    def _body(self):
        """The request's JSON object, or None after answering 400 itself."""
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = -1
        if not 0 < length <= MAX_CODE + 4096:
            self._json(413, {"error": "corps trop gros ou vide"})
            return None
        try:
            data = json.loads(self.rfile.read(length))
        except ValueError:
            data = None
        if not isinstance(data, dict):
            self._json(400, {"error": "requête malformée"})
            return None
        return data

    def _entry(self, data):
        """The catalogue entry named by this request, or None after a 400.

        Going through find_tp() and not through the raw string is what keeps an
        exercise id out of the database that the catalogue does not know about.
        """
        entry = find_tp(str(data.get("tp", "")))
        if entry is None:
            self._json(400, {"error": "TP inconnu"})
        return entry

    def _throttle(self):
        """True when this caller has to slow down (and has been told so).

        A separate limiter from the submission one: a draft is written every few
        seconds while typing, a compilation every fifteen. One ceiling for both
        would either forbid the first or wave the second through.
        """
        who = client_id(self.headers, self.client_address[0])
        with self.lock:
            wait = self.state_quota.check(who, time.time())
        if wait:
            self._json(429, {"error": f"trop d'écritures -- réessaie dans {wait} s",
                             "retry_after": wait})
        return bool(wait)

    def _states(self):
        sub = self._who()
        if sub is None:
            return
        states = etat.read_states(sub)
        if states is None:
            self._json(503, {"error": "la base ne répond pas"})
            return
        self._json(200, {"etats": states})

    def _read_draft(self):
        sub = self._who()
        if sub is None:
            return
        query = self.path.split("?", 1)[1] if "?" in self.path else ""
        wanted = ""
        for pair in query.split("&"):
            if pair.startswith("ex="):
                wanted = urllib.parse.unquote(pair[3:])
        if find_tp(wanted) is None:
            self._json(400, {"error": "TP inconnu"})
            return
        # An absent draft is not an error: it is a student opening an exercise
        # for the first time. `sources: null` says so without dressing it up.
        self._json(200, {"sources": etat.read_resume(sub, wanted)})

    def do_PUT(self):  # noqa: N802 -- imposé par BaseHTTPRequestHandler
        path = self.path.split("?", 1)[0]
        if path not in ("/brouillon", "/etat"):
            self._json(404, {"error": "inconnu"})
            return
        sub = self._who()
        if sub is None:
            return
        data = self._body()
        if data is None:
            return
        entry = self._entry(data)
        if entry is None:
            return
        files, message, status = validate_files(entry, data.get("files"))
        if message:
            self._json(status, {"error": message})
            return
        if self._throttle():
            return
        if path == "/brouillon":
            ok = etat.write_draft(sub, entry["id"], files)
        else:
            status_name = str(data.get("statut", ""))
            if status_name not in etat.STATUSES:
                self._json(400, {"error": "statut inconnu"})
                return
            ok = etat.write_state(sub, entry["id"], status_name, files)
        # The page shows "saved" only on a true answer, so this boolean has to
        # mean what it says: a database that did not write must not answer 200.
        if not ok:
            self._json(503, {"error": "la base ne répond pas"})
            return
        self._json(200, {"ok": True})

    def do_DELETE(self):  # noqa: N802 -- imposé par BaseHTTPRequestHandler
        """Erase everything stored for this student.

        The consent sentence shown before the redirect to Rauthy promises this
        exists, so it exists -- not "later".
        """
        if self.path.split("?", 1)[0] != "/moi":
            self._json(404, {"error": "inconnu"})
            return
        sub = self._who()
        if sub is None:
            return
        if not etat.forget(sub):
            self._json(503, {"error": "la base ne répond pas"})
            return
        self._json(200, {"ok": True})

    def _quiz(self, tp):
        """Les questions d'un quiz, telles que le worker les a publiées.

        Le chemin est reconstruit à partir du catalogue, jamais concaténé depuis
        l'URL : `find_tp` refuse tout ce qui n'est pas un TP existant, donc il
        n'y a pas de chemin à traverser.
        """
        entry = find_tp(tp)
        if entry is None or entry.get("mode") != "quiz":
            self._json(404, {"error": "pas un quiz"})
            return
        self._file(os.path.join("quiz", entry["id"] + ".json"),
                   "application/json; charset=utf-8")

    def _result(self, job_id):
        if not JOB_RE.match(job_id):
            self._json(400, {"error": "identifiant invalide"})
            return
        path = os.path.join(SPOOL, job_id, "result.json")
        try:
            with open(path, encoding="utf-8") as fh:
                self._json(200, json.load(fh))
                return
        except OSError:
            pass
        except ValueError:
            # Le worker écrit result.json par rename atomique, donc ce cas ne
            # devrait pas exister. S'il arrive, c'est un bug du worker et pas
            # une course : le dire plutôt que de boucler indéfiniment.
            self._json(500, {"state": "error", "message": "verdict illisible"})
            return
        # Le .lock est posé par le worker qui a pris le job. Sans ce test, un job
        # en cours de compilation s'afficherait « 1er dans la file » jusqu'au
        # verdict -- exact au sens du rang, faux au sens de ce qui se passe.
        if os.path.exists(os.path.join(SPOOL, job_id, ".lock")):
            self._json(200, {"state": "running"})
            return
        rank = queue_position(scan_jobs(), job_id)
        if rank:
            self._json(200, {"state": "queued", "position": rank})
        else:
            # Balayé par le worker (10 minutes) ou n'a jamais existé.
            self._json(404, {"state": "gone"})

    def do_POST(self):  # noqa: N802 -- imposé par BaseHTTPRequestHandler
        if self.path.split("?", 1)[0] != "/submit":
            self._json(404, {"error": "inconnu"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = -1
        if not 0 < length <= MAX_CODE + 4096:
            self._json(413, {"error": "soumission trop grosse ou vide"})
            return
        try:
            data = json.loads(self.rfile.read(length))
            key = str(data["key"])
            tp = str(data["tp"])
        except (ValueError, KeyError, TypeError):
            self._json(400, {"error": "requête malformée"})
            return

        # La clé D'ABORD, en temps constant, et avant tout travail : rien ne
        # doit être mesurable depuis l'extérieur sans elle.
        if not KEY or not hmac.compare_digest(key, KEY):
            self._json(403, {"error": "clé de session invalide ou expirée"})
            return
        entry = find_tp(tp)
        if entry is None:
            self._json(400, {"error": "TP inconnu"})
            return

        # Le mode décide de ce qui est attendu et du nom du fichier déposé dans
        # le spool. Le worker lit l'un ou l'autre selon le mode qu'il déduit du
        # répertoire de tests : les deux côtés tombent d'accord par le catalogue,
        # pas par un champ que le client aurait pu choisir.
        if entry.get("mode") == "quiz":
            answers = data.get("answers")
            if not isinstance(answers, dict):
                self._json(400, {"error": "réponses manquantes"})
                return
            # Bornées en nombre ET en longueur : une réponse est une poignée de
            # caractères, et Content-Length ne suffit pas à empêcher un
            # dictionnaire de dix mille clés d'une lettre.
            trimmed = {str(k)[:64]: str(v)[:64]
                       for k, v in list(answers.items())[:500]}
            if not any(v.strip() for v in trimmed.values()):
                self._json(400, {"error": "aucune réponse saisie"})
                return
            name, blob = "answers.json", json.dumps(trimmed).encode()
        else:
            # The whitelist lives in validate_files() because a draft goes
            # through exactly the same one. Two copies of "which names are
            # allowed" would drift apart, and the copy that drifts is the one
            # that lets an unexpected file name through.
            files, message, status = validate_files(entry, data.get("files"))
            if message:
                self._json(status, {"error": message})
                return
            if not any(v.strip() for v in files.values()):
                self._json(400, {"error": "soumission vide"})
                return
            blob, name = json.dumps(files).encode(), "files.json"

        who = client_id(self.headers, self.client_address[0])
        with self.lock:
            wait = self.quota.check(who, time.time())
            if wait:
                self._json(
                    429,
                    {
                        "error": f"trop de soumissions -- réessaie dans {wait} s",
                        "retry_after": wait,
                    },
                )
                return
            pending = sum(1 for _, _, done in scan_jobs() if not done)
            if pending >= QUEUE_MAX:
                self._json(503, {"error": "file pleine -- réessaie dans une minute"})
                return
            # L'écriture reste SOUS le verrou : sinon le plafond de file se fait
            # dépasser par le nombre de requêtes concurrentes, ce qui est
            # exactement la situation qu'il existe pour couvrir. Écrire 64 Ko en
            # tenant un verrou global coûte moins que de raisonner sur la course.
            job_id = self._spool(tp, name, blob)

        self._json(200, {"id": job_id})

    def _spool(self, tp, name, blob):
        """Écrit le job. job.json EN DERNIER, par rename atomique.

        Le worker ne déclenche que sur la présence de job.json. Sans cet ordre
        il lirait un submission.c à moitié écrit et rendrait une erreur de
        compilation fantôme, une fois sur cent, à l'étudiant qui n'y est pour
        rien.
        """
        job_id = uuid.uuid4().hex
        path = os.path.join(SPOOL, job_id)
        os.mkdir(path, 0o755)
        with open(os.path.join(path, name), "wb") as fh:
            fh.write(blob)
        tmp = os.path.join(path, "job.json.tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"tp": tp}, fh)
        os.replace(tmp, os.path.join(path, "job.json"))
        return job_id


def main():
    if not KEY:
        raise SystemExit("CTESTER_KEY est vide : le service refuse de démarrer")
    # A misconfigured optional feature must NOT take the judge down with it: it
    # says so loudly in `docker logs` and stays off. Refusing to boot here would
    # mean a typo in an OIDC variable stops every student from testing code.
    if OIDC_ISSUER and not oidc_enabled():
        print("connexion desactivee : il faut CTESTER_OIDC_ISSUER en https,"
              " CTESTER_OIDC_CLIENT_ID et CTESTER_DB_DSN", file=sys.stderr)
    os.makedirs(SPOOL, exist_ok=True)
    ThreadingHTTPServer(("", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
