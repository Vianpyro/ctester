#!/usr/bin/env python3
"""ctester -- l'API du juge C. Fichier géré par Ansible : éditer le rôle.

Ce processus ne compile RIEN et n'exécute RIEN. Il valide une soumission,
l'écrit dans le spool, et lit le verdict qu'un worker de l'hôte y dépose. Il
n'a ni le socket Docker, ni accès au répertoire des tests -- c'est toute la
raison pour laquelle il peut être exposé à Internet.

Bibliothèque standard uniquement : rien à installer au démarrage, rien à
patcher, et l'image officielle python:3.13-slim suffit telle quelle.
"""

import hmac
import json
import os
import re
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock

SPOOL = os.environ.get("CTESTER_SPOOL", "/spool")
STATIC = os.environ.get("CTESTER_STATIC", "/app")
KEY = os.environ.get("CTESTER_KEY", "")
COOLDOWN = int(os.environ.get("CTESTER_COOLDOWN", "15"))
HOURLY = int(os.environ.get("CTESTER_HOURLY_QUOTA", "40"))
QUEUE_MAX = int(os.environ.get("CTESTER_QUEUE_MAX", "60"))
MAX_CODE = int(os.environ.get("CTESTER_MAX_CODE_BYTES", "65536"))
PORT = int(os.environ.get("CTESTER_PORT", "8000"))

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
        else:
            self._json(404, {"error": "inconnu"})

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
            blob = str(data.get("code", "")).encode("utf-8", "replace")
            if not blob.strip():
                self._json(400, {"error": "soumission vide"})
                return
            if len(blob) > MAX_CODE:
                self._json(413, {"error": f"fichier > {MAX_CODE // 1024} Ko"})
                return
            name = "submission.c"

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
    os.makedirs(SPOOL, exist_ok=True)
    ThreadingHTTPServer(("", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
