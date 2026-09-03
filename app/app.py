#!/usr/bin/env python3
"""ctester -- l'API du juge C. Fichier géré par Ansible : éditer le rôle.

Ce processus ne compile RIEN et n'exécute RIEN. Il valide une soumission,
l'écrit dans le spool, et lit le verdict qu'un worker de l'hôte y dépose. Il
n'a ni le socket Docker, ni accès au répertoire des tests -- c'est toute la
raison pour laquelle il peut être exposé à Internet.

Bibliothèque standard uniquement : rien à installer au démarrage, rien à
patcher, et l'image officielle python:3.13-slim suffit telle quelle.
"""

import base64
import gzip
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
import politique

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

# --- Forum d'entraide (MVP) -------------------------------------------------
# ÉTEINT PAR DÉFAUT, ET C'EST LE RÉGLAGE SÛR. Sans au moins un `sub` de
# modérateur configuré, `forum_enabled()` est faux : le bouton n'apparaît pas,
# `forum.js` n'est jamais demandé, et les routes répondent 503 en le disant. Un
# forum sans personne pour le modérer est un canal de partage de solutions avec
# une charte dessus -- on ne l'ouvre pas « en attendant ».
#
# DES `sub` OIDC OPAQUES, séparés par virgule ou espace, JAMAIS un claim du
# jeton : un rôle dérivé d'un claim non vérifié se réclame depuis un compte que
# l'on contrôle. Voir le runbook du rôle Ansible pour relever ces valeurs sans
# les écrire dans le dépôt ni les exposer au navigateur.
FORUM_MODERATORS = frozenset(
    s for s in re.split(r"[,\s]+",
                        os.environ.get("CTESTER_FORUM_MODERATORS", "")) if s)
FORUM_MAX_CHARS = int(os.environ.get("CTESTER_FORUM_MAX_CHARS", "1200"))
FORUM_COOLDOWN = int(os.environ.get("CTESTER_FORUM_COOLDOWN", "10"))
FORUM_HOURLY = int(os.environ.get("CTESTER_FORUM_HOURLY_QUOTA", "20"))
# Borne de LECTURE d'un fil et de la file de modération. Un fil d'exercice à 27
# étudiants n'en approche pas ; la borne existe pour que la page ne puisse pas
# recevoir un objet sans fin le jour où quelque chose tourne mal.
FORUM_MAX_FIL = 200

# LES DEUX BIBLIOTHÈQUES DU RENDU, ÉPINGLÉES DANS LEUR NOM DE FICHIER. Elles
# vivent dans le dépôt (`app/vendor/`, voir son README) et sont servies depuis
# cette origine : la CSP dit `script-src 'self'`, donc un CDN serait bloqué, et
# c'est voulu. Monter de version demande de toucher à cette liste ET à
# `forum.js` -- une mise à jour d'assainisseur HTML ne doit pas se faire par
# accident.
VENDOR = ("vendor/marked-18.0.11.umd.js", "vendor/purify-3.4.14.min.js")

TP_RE = re.compile(r"\A[a-z0-9_-]{1,32}\Z")
JOB_RE = re.compile(r"\A[0-9a-f]{32}\Z")
# Les identifiants de message et d'action ont la même forme qu'un job (uuid4
# hexadécimal), mais ce n'est pas la même chose : les confondre dans une seule
# constante ferait qu'un jour où l'une des deux formes change, l'autre changerait
# en silence avec elle.
MSG_RE = re.compile(r"\A[0-9a-f]{32}\Z")


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


def job_metadata(job_id):
    """The server-owned exercise and optional OIDC subject for one spool job.

    `owner` is written after validating the bearer token at submission time;
    it is never accepted from browser JSON.  Malformed/old jobs simply have no
    owner so the anonymous judge keeps its historical behaviour.
    """
    try:
        with open(os.path.join(SPOOL, job_id, "job.json"), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return "", None
    if not isinstance(data, dict):
        return "", None
    tp = str(data.get("tp", ""))
    owner = data.get("owner")
    if not isinstance(owner, str) or not 0 < len(owner) <= 128:
        owner = None
    return tp, owner


def job_sources(job_id, entry):
    """The submitted source snapshot needed by the legacy exercise state.

    It is read only for a job whose owner was fixed by the API at submission.
    Quiz answers are not source files and intentionally keep the existing empty
    snapshot; compiled submissions use the same catalogue whitelist as every
    other path.
    """
    if entry.get("mode") == "quiz":
        return {}
    try:
        with open(os.path.join(SPOOL, job_id, "files.json"), encoding="utf-8") as fh:
            submitted = json.load(fh)
    except (OSError, ValueError):
        return {}
    files, message, _ = validate_files(entry, submitted)
    return files if message is None else {}


# --- Progression (phase 1) --------------------------------------------------
# XP, niveau, compétences pratiquées et recommandation, pour les comptes
# connectés SEULEMENT. Rien ici ne touche au verdict, au bac à sable, au
# catalogue public ni au parcours anonyme : ce sont des lectures de faits que
# le serveur a lui-même écrits, plus les métadonnées publiques du catalogue.
#
# LES CHIFFRES SONT DANS politique.py. Aucune valeur d'équilibrage n'a le droit
# d'apparaître dans ce fichier : piloter le semestre doit rester une édition de
# la politique, pas une relecture de l'API.

MAX_SKILLS = 40


def exercise_facts(states, practice):
    """(pratiqués, réussis) : deux ensembles d'identifiants d'exercice.

    Les deux sources sont fusionnées. `tentative_pratique` sait qu'un job a été
    jugé, `etat_exercice` sait où en est l'exercice ; un compte antérieur aux
    tentatives n'a que la seconde et doit quand même compter.
    """
    touched, solved = set(), set()
    for row in states or ():
        exercise = row.get("exercice_id")
        if not exercise:
            continue
        touched.add(exercise)
        if row.get("statut") == "valide":
            solved.add(exercise)
    for row in practice or ():
        exercise = row.get("exercice_id")
        if exercise:
            touched.add(exercise)
    return touched, solved


def skills_view(entries, touched, solved):
    """[{id, total, pratiques, reussis}] dans l'ordre du cours.

    « PRATIQUÉE », JAMAIS « MAÎTRISÉE ». Ce compteur dit qu'un exercice
    portant cette compétence a été soumis et jugé, rien de plus : le juge est en
    libre service et aucune vérification indépendante n'existe en phase 1.
    L'écart entre les deux est le sujet entier de docs/gamification/mastery.md,
    et le jour où on l'oublie dans un libellé, on a promis une note.
    """
    order, table = [], {}
    for entry in entries:
        for skill in (entry.get("learning") or {}).get("skills") or ():
            row = table.get(skill)
            if row is None:
                row = table[skill] = {"id": skill, "total": 0,
                                      "pratiques": 0, "reussis": 0}
                order.append(row)
            row["total"] += 1
            row["pratiques"] += int(entry["id"] in touched)
            row["reussis"] += int(entry["id"] in solved)
    return order[:MAX_SKILLS]


def practised_skills(entries, touched):
    """Les compétences qu'un exercice touché a fait pratiquer."""
    skills = set()
    for entry in entries:
        if entry["id"] in touched:
            skills.update((entry.get("learning") or {}).get("skills") or ())
    return skills


def recommander(entries, touched, solved):
    """Le prochain exercice à ouvrir, ou None. DÉTERMINISTE : l'ordre du cours.

    D'abord un exercice publié non réussi qui reprend une compétence déjà
    pratiquée -- consolider passe avant découvrir ; sinon le premier non réussi ;
    sinon rien, et la page le dit plutôt que d'inventer une suite.
    """
    known = practised_skills(entries, touched)
    remaining = [e for e in entries if e["id"] not in solved]
    for entry in remaining:
        for skill in (entry.get("learning") or {}).get("skills") or ():
            if skill in known:
                return {"exercice_id": entry["id"], "competence": skill}
    if remaining:
        return {"exercice_id": remaining[0]["id"], "competence": None}
    return None


def progression_facts(user):
    """Les compteurs dont dépendent les succès. None si la base ne répond pas.

    Bornés au catalogue publié : un exercice retiré ne doit plus rien débloquer.
    """
    states = etat.read_states(user)
    practice = etat.read_practice_summary(user)
    if states is None or practice is None:
        return None
    entries = load_tps()
    touched, solved = exercise_facts(states, practice)
    published = {e["id"] for e in entries}
    return {"reussites": len(solved & published),
            "competences": len(practised_skills(entries, touched))}


def recompenser(user, entry, job_id):
    """Une PREMIÈRE réussite complète -> au plus une attribution d'XP.

    Appelée par le serveur quand il lit un verdict complet, jamais par le
    navigateur. Trois règles y tiennent d'un coup :

    - un échec ne rapporte rien : l'appelant n'appelle que sur `solved` ;
    - refaire le même exercice ne rapporte rien -- l'identifiant d'événement est
      « reussite:<exercice> » et sa clé primaire refuse le doublon ;
    - un sondage rejoué ne rapporte rien : même identifiant, même refus.

    Rien ne se célèbre quand `grant_first_solve` rend None -- déjà récompensé,
    ou base muette. Les deux veulent dire « il n'y a pas de fait neuf ».
    """
    learning = entry.get("learning") or {}
    event_id = "reussite:" + entry["id"]
    granted = etat.grant_first_solve(
        user, entry["id"], event_id, politique.xp_reussite(learning),
        "première réussite de l'exercice", politique.VERSION,
        {"job": job_id, "difficulte": learning.get("difficulty", "")},
        politique.plafond_quotidien())
    if granted is None:
        return
    facts = progression_facts(user)
    if facts is not None:
        etat.unlock(user, politique.succes_atteints(facts), event_id,
                    politique.VERSION)


def progress_payload(entries, facts, states, practice):
    """Le contrat de GET /progres : borné, dérivé, et sans rien de secret.

    Ni code soumis, ni détail de verdict, ni chemin de tests : des compteurs,
    des identifiants publics du catalogue, et les libellés de succès que porte
    la politique. `politique` voyage avec, pour qu'un écran sache de quelle
    version des chiffres il parle.
    """
    touched, solved = exercise_facts(states, practice)
    return {
        "politique": politique.VERSION,
        "xp": facts["xp"],
        "niveau": politique.niveau(facts["xp"]),
        "exercices": {
            "total": len(entries),
            "pratiques": sum(1 for e in entries if e["id"] in touched),
            "reussis": sum(1 for e in entries if e["id"] in solved),
        },
        "competences": skills_view(entries, touched, solved),
        # Un identifiant stocké dont la politique ne connaît plus la définition
        # ne s'affiche pas -- il n'est pas perdu pour autant, il reste en base.
        "succes": [{"id": row["id"],
                    "titre": politique.SUCCES[row["id"]]["titre"],
                    "description": politique.SUCCES[row["id"]]["description"],
                    "obtenu_le": row["obtenu_le"]}
                   for row in facts["succes"] if row["id"] in politique.SUCCES],
        "suivant": recommander(entries, touched, solved),
        # La consultation/export des attributions, déjà bornée par etat.py.
        "transactions": facts["transactions"],
    }


# --- Forum d'entraide (MVP) -------------------------------------------------
# UN fil chronologique par exercice PUBLIÉ, privé aux comptes connectés. Rien
# ici ne produit de valeur de jeu : pas d'XP, pas de succès, pas de compteur, et
# la progression de la phase 1 n'est ni lue ni écrite depuis ces routes.
#
# LA MODÉRATION EST HUMAINE, ET ON NE PRÉTEND PAS L'INVERSE. Il n'y a pas de
# détecteur de solution : les seules règles automatiques sont des bornes
# (longueur, quota) et le refus des liens, qui est une règle de la charte -- pas
# un jugement sur le contenu. Tout le reste passe par un signalement et par
# quelqu'un qui lit.


def forum_enabled():
    """True quand le forum peut être offert. FAUX par défaut.

    Il faut la connexion (donc l'émetteur, le client et la base) ET au moins un
    modérateur configuré. La seconde condition n'est pas cosmétique : le
    signalement doit aboutir chez quelqu'un, sinon on offre un canal public sans
    recours.
    """
    return oidc_enabled() and bool(FORUM_MODERATORS)


def is_moderator(sub):
    """Le contrôle de rôle, et il est ICI -- jamais dans le navigateur.

    La page reçoit bien un drapeau `moderateur`, mais c'est un drapeau
    d'AFFICHAGE : chaque route de modération le recalcule à partir du `sub`
    authentifié. Un booléen retourné par un client n'est pas une autorisation.
    """
    return bool(sub) and sub in FORUM_MODERATORS


def forum_texte(brut):
    """(texte, message d'erreur) -- du Markdown restreint, court, et rien d'autre.

    CE QUI EST STOCKÉ EST LA SOURCE, PAS DU HTML. Le serveur ne rend rien et
    n'assainit rien : il borne. Le rendu -- Markdown puis assainisseur -- se
    fait au moment de l'AFFICHAGE, à chaque affichage, dans `forum.js`. Assainir
    à l'écriture seulement serait la mauvaise moitié du travail : une règle
    resserrée plus tard ne s'appliquerait pas aux messages déjà en base.

    Les caractères de contrôle partent quand même : ils ne servent à rien dans
    du Markdown, ils compliquent une relecture humaine, et ils n'ont aucune
    raison d'attendre le navigateur pour disparaître.
    """
    if not isinstance(brut, str):
        return None, "message manquant"
    texte = brut.replace("\r\n", "\n")
    texte = "".join(c for c in texte if c in "\n\t" or c >= " ").strip()
    if not texte:
        return None, "un message vide n'aide personne"
    if len(texte) > FORUM_MAX_CHARS:
        return None, f"message trop long (maximum {FORUM_MAX_CHARS} caractères)"
    return texte, None


def forum_vue(messages, sub, moderateur):
    """Ce qu'un fil devient pour CET appelant. AUCUN `sub` ne franchit cette ligne.

    « Vous » pour son auteur, « Participant » pour les autres, « Équipe du
    cours » pour un modérateur : trois mots dérivés ici, et la page ne reçoit
    rien qui permette de recoller deux messages au même étudiant. Pas de
    pseudonyme persistant non plus -- ce serait une identité, en plus petit.

    Les messages masqués ne sortent QUE vers un modérateur : c'est lui qui doit
    pouvoir les rétablir.
    """
    return [{"id": m["id"], "texte": m["texte"], "cree_le": m["cree_le"],
             "auteur": ("Vous" if m["utilisateur"] == sub
                        else "Équipe du cours"
                        if is_moderator(m["utilisateur"]) else "Participant"),
             "mien": m["utilisateur"] == sub,
             "masque": m["masque"]}
            for m in messages if moderateur or not m["masque"]]


# --- La CSP du document -----------------------------------------------------
# CE N'EST PAS LA DÉFENSE PRINCIPALE, et il faut le lire comme ça. Ce qui
# empêche le HTML d'un étudiant de s'exécuter, c'est l'assainisseur épinglé de
# `forum.js` et le fait que tout le reste de la page passe par `textContent`.
# La CSP est la couche qui limite les dégâts si l'une de ces deux-là cède : elle
# transforme une injection réussie en injection qui ne peut ni charger un script
# d'ailleurs, ni parler à un autre hôte, ni s'encadrer.
#
# LE HACHAGE DU SCRIPT DE THÈME EST CALCULÉ SUR LE CORPS SERVI, pas écrit à la
# main. Ce script DOIT rester inline (il pose le thème avant le premier rendu,
# voir index.html) ; un hachage recopié se périmerait à la première virgule
# changée, et la page repartirait sans thème avec une erreur de console que
# personne ne lit.
_INLINE_SCRIPT_RE = re.compile(rb"<script(?![^>]*\ssrc=)[^>]*>(.*?)</script>",
                               re.DOTALL)


def csp(body, issuer=""):
    """La politique de sécurité du contenu pour CE document HTML.

    `style-src` garde `'unsafe-inline'` : la page pose des attributs `style`
    calculés (la largeur d'une jauge, le rang d'une coche de verdict). Ce sont
    des styles, pas des scripts, et les retirer demanderait de réécrire trois
    composants pour un gain nul face à la menace visée ici.

    `connect-src` doit contenir l'émetteur OIDC : `compte.js` va y chercher le
    document de découverte puis le jeton. Sans lui, la connexion échoue en
    silence -- et c'est le genre de panne qu'une CSP produit sans le dire.
    """
    empreintes = " ".join(
        "'sha256-" + base64.b64encode(hashlib.sha256(bloc).digest()).decode() + "'"
        for bloc in _INLINE_SCRIPT_RE.findall(body) if bloc.strip())
    origine = ""
    if issuer.startswith("https://"):
        origine = " " + "/".join(issuer.split("/")[:3])
    return "; ".join([
        "default-src 'none'",
        ("script-src 'self' " + empreintes).strip(),
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self'",
        "connect-src 'self'" + origine,
        "base-uri 'none'",
        "form-action 'none'",
        "frame-ancestors 'none'",
    ])


class Handler(BaseHTTPRequestHandler):
    server_version = "ctester"
    quota = Quota(COOLDOWN, HOURLY)
    # Draft and state writes are cheap -- no compiler, no container -- so they
    # get their own, far looser limiter. It exists to bound abuse, not to pace
    # a student who types.
    state_quota = Quota(cooldown=1, hourly=1200)
    # Le forum a le sien, compté PAR COMPTE et pas par IP, et il couvre les
    # écritures seulement -- publier et signaler. Sobre exprès : il freine une
    # rafale, il n'empêche ni de lire un fil ni de soumettre du C.
    forum_quota = Quota(FORUM_COOLDOWN, FORUM_HOURLY)
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

    def handle_one_request(self):
        self._corps_lu = False
        BaseHTTPRequestHandler.handle_one_request(self)

    def _vider(self):
        """Lit et jette le corps d'une requête à laquelle on répond sans lui.

        EN HTTP/1.1 LA CONNEXION EST RÉUTILISÉE (voir `protocol_version`), et un
        corps laissé dans la socket est lu comme la LIGNE DE REQUÊTE suivante :
        le navigateur récolte alors un 400 sur une requête parfaitement valide,
        et le journal du conteneur se remplit de « Bad request version ».
        Ça arrive dès qu'un PUT ou un POST se fait refuser AVANT `_body()` --
        jeton expiré, forum éteint, rôle insuffisant -- c'est-à-dire au plus
        mauvais moment, quand l'étudiant réessaie.
        """
        if self._corps_lu:
            return
        self._corps_lu = True
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0:
            return
        # Au-delà de ce que `_body` accepterait, on ne vide pas : on ferme. Lire
        # pour jeter un corps sans limite serait un déni de service offert.
        if length > MAX_CODE + 4096:
            self.close_connection = True
            return
        try:
            self.rfile.read(length)
        except Exception:
            self.close_connection = True

    def _json(self, code, payload):
        self._vider()
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
        self._send_file(body, ctype)

    def _send_file(self, body, ctype, envoyer=True):
        """Un fichier statique, revalidé à chaque visite, transféré si besoin.

        `no-cache` NE VEUT PAS DIRE « ne pas mettre en cache » : il veut dire
        « garde-le, mais redemande-moi avant de t'en servir ». Le navigateur
        repasse donc systématiquement, et un correctif déployé se voit toujours
        tout de suite -- c'est ce que `no-store` protégeait, et c'est intact.
        Ce qui change, c'est qu'un fichier inchangé revient en 304 vide au lieu
        de repartir en entier : la page, sa feuille et son script font 65 Ko, et
        un étudiant recharge beaucoup.

        `no-store` interdisait AUSSI le cache aller-retour du navigateur
        (bfcache) : avec lui, le bouton Retour refaisait toute la page.
        """
        etiquette = '"' + hashlib.sha256(body).hexdigest()[:16]
        # LA CSP EST CALCULÉE SUR LE CORPS EN CLAIR, avant la compression : le
        # hachage porte sur le script inline du document, pas sur son transport.
        politique = (csp(body, OIDC_ISSUER)
                     if ctype.startswith("text/html") else "")
        # UNE ÉTIQUETTE PAR REPRÉSENTATION. Deux corps différents pour une même
        # URL -- l'original et le gzip -- ne peuvent pas partager un ETag : un
        # cache intermédiaire servirait l'un en croyant valider l'autre.
        comprime = (len(body) >= 1024
                    and "gzip" in self.headers.get("Accept-Encoding", ""))
        if comprime:
            body = gzip.compress(body, 6)
            etiquette += "-gz"
        etiquette += '"'

        if self.headers.get("If-None-Match") == etiquette:
            self.send_response(304)
            self.send_header("ETag", etiquette)
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Vary", "Accept-Encoding")
            # SUR LE 304 AUSSI. Le navigateur rejoue la réponse gardée en la
            # mettant à jour avec ces en-têtes ; une CSP qui n'apparaîtrait que
            # sur le 200 disparaîtrait donc dès la deuxième visite, c'est-à-dire
            # presque toujours.
            if politique:
                self.send_header("Content-Security-Policy", politique)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("ETag", etiquette)
        self.send_header("Vary", "Accept-Encoding")
        if politique:
            self.send_header("Content-Security-Policy", politique)
        if comprime:
            self.send_header("Content-Encoding", "gzip")
        self.end_headers()
        if envoyer:
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
            # LES MÊMES EN-TÊTES QUE do_GET, ETag et encodage compris : un HEAD
            # qui annonce une autre étiquette que le GET est un piège à
            # revalidation. D'où le même code, sans le corps.
            try:
                with open(os.path.join(STATIC, "index.html"), "rb") as fh:
                    body = fh.read()
            except OSError:
                self.send_response(500)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self._send_file(body, "text/html; charset=utf-8", envoyer=False)

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
        elif path == "/style.css":
            self._file("style.css", "text/css; charset=utf-8")
        elif path == "/favicon.svg":
            self._file("favicon.svg", "image/svg+xml")
        elif path in ("/app.js", "/quiz.js", "/compte.js", "/progres.js",
                      "/forum.js"):
            # Liste close, pas un suffixe : `.js` n'ouvre pas le répertoire.
            self._file(path[1:], "text/javascript; charset=utf-8")
        elif path[1:] in VENDOR:
            # Les deux bibliothèques du rendu, servies depuis cette origine et
            # sous leur nom versionné. `VENDOR` est une liste close comme
            # au-dessus : `/vendor/` n'est pas un répertoire ouvert.
            self._file(path[1:], "text/javascript; charset=utf-8")
        elif path == "/tps.json":
            # RELU À CHAQUE FOIS, pas mis en cache au démarrage : publier un
            # nouveau TP est alors `--tags tests` et rien d'autre. Une valeur
            # en cache voudrait dire recréer le conteneur pour ajouter une
            # ligne à un menu déroulant, et c'est le genre d'étape qu'on oublie
            # le soir où on ajoute le TP4.
            self._send_file(
                json.dumps(load_tps()).encode(),
                "application/json; charset=utf-8")
        elif path.startswith("/quiz/") and path.endswith(".json"):
            self._quiz(path[6:-5])
        elif path.startswith("/tp/") and path.endswith(".json"):
            self._detail(path[4:-5])
        elif path.startswith("/r/"):
            self._result(path[3:])
        elif path == "/oidc.json":
            # The page asks this before showing anything: an empty object means
            # "no sign-in here", and it then behaves exactly as it always did.
            # `forum` voyage ici parce que c'est déjà l'endpoint « ce qui est
            # offert sur ce déploiement », lu avant que la page n'affiche quoi
            # que ce soit. Faux ou absent : le bouton n'existe pas et
            # `forum.js` n'est jamais demandé.
            self._json(200, {"issuer": OIDC_ISSUER, "client_id": OIDC_CLIENT_ID,
                             "forum": forum_enabled()}
                            if oidc_enabled() else {})
        elif path == "/etats":
            self._states()
        elif path == "/pratique":
            self._practice()
        elif path == "/progres":
            self._progress()
        elif path == "/brouillon":
            self._read_draft()
        elif path == "/forum":
            self._forum_fil()
        elif path == "/forum/moderation":
            self._forum_file_moderation()
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
            self._corps_lu = True
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

    def _practice(self):
        sub = self._who()
        if sub is None:
            return
        summary = etat.read_practice_summary(sub)
        if summary is None:
            self._json(503, {"error": "la base ne répond pas"})
            return
        self._json(200, {"pratique": summary})

    def _progress(self):
        """La progression privée d'un compte : XP, niveau, compétences, succès.

        AUCUN IDENTIFIANT D'UTILISATEUR N'EST ACCEPTÉ DU CLIENT -- `_who()` est
        la seule source, comme partout ailleurs ici. Ce que la page reçoit est
        une PROJECTION recalculée à chaque appel depuis les faits de la base et
        le catalogue public ; le navigateur ne calcule ni solde, ni niveau, ni
        déblocage, et ne peut donc pas en déclarer.
        """
        sub = self._who()
        if sub is None:
            return
        facts = etat.read_progress(sub)
        states = etat.read_states(sub)
        practice = etat.read_practice_summary(sub)
        # Une base muette se dit. Inventer un solde à zéro ferait croire à un
        # étudiant que son travail a disparu.
        if facts is None or states is None or practice is None:
            self._json(503, {"error": "la base ne répond pas"})
            return
        self._json(200, progress_payload(load_tps(), facts, states, practice))

    def _read_draft(self):
        sub = self._who()
        if sub is None:
            return
        wanted = self._param("ex")
        if find_tp(wanted) is None:
            self._json(400, {"error": "TP inconnu"})
            return
        # An absent draft is not an error: it is a student opening an exercise
        # for the first time. `sources: null` says so without dressing it up.
        self._json(200, {"sources": etat.read_resume(sub, wanted)})

    # --- Forum d'entraide ---------------------------------------------------
    # Six routes, toutes derrière `_forum_qui()`, qui est le `_who()` habituel
    # plus la condition d'activation. AUCUNE ne prend d'identifiant
    # d'utilisateur dans la requête, et aucune ne balaye les données de tous
    # les étudiants : on lit UN fil d'exercice, ou la file des signalements.
    #
    # LE FORUM NE DOIT JAMAIS EMPÊCHER DE FAIRE UN EXERCICE. Une base muette,
    # un forum éteint ou une panne ici répondent 503 en le disant, et « Tester »
    # continue de marcher -- c'est ce que `test_page.js` éprouve.

    def _param(self, name):
        """La valeur d'un paramètre de requête, décodée. Chaîne vide si absent."""
        query = self.path.split("?", 1)[1] if "?" in self.path else ""
        for pair in query.split("&"):
            if pair.startswith(name + "="):
                return urllib.parse.unquote(pair[len(name) + 1:])
        return ""

    def _forum_qui(self):
        """Le `sub` de l'appelant, ou None après avoir répondu 503/401 lui-même."""
        if not forum_enabled():
            self._json(503, {"error": "les discussions ne sont pas activées "
                                      "sur ce déploiement"})
            return None
        return self._who()

    def _forum_moderateur(self):
        """Le `sub` d'un modérateur, ou None après un 401/403/503.

        LE RÔLE EST RECALCULÉ ICI, À CHAQUE APPEL, DEPUIS LE `sub` AUTHENTIFIÉ.
        La page reçoit bien un drapeau, mais il ne sert qu'à décider quoi
        dessiner : aucune de ces deux routes ne le croit sur parole.
        """
        sub = self._forum_qui()
        if sub is None:
            return None
        if not is_moderator(sub):
            self._json(403, {"error": "réservé à l'équipe du cours"})
            return None
        return sub

    def _forum_entree(self, brut):
        """L'entrée de catalogue nommée, ou None après un 400.

        `find_tp` est la SEULE porte : il n'existe pas de fil pour un exercice
        absent du catalogue, donc pas de fil à créer avec un identifiant
        fabriqué, et pas de chemin à traverser.
        """
        entry = find_tp(str(brut or ""))
        if entry is None:
            self._json(400, {"error": "TP inconnu"})
        return entry

    def _forum_message_id(self, brut):
        """Un identifiant de message bien formé, ou None après un 400."""
        message_id = str(brut or "")
        if not MSG_RE.match(message_id):
            self._json(400, {"error": "identifiant invalide"})
            return None
        return message_id

    def _forum_throttle(self, sub):
        """True quand ce COMPTE doit ralentir (et vient de l'apprendre).

        PAR `sub`, PAS PAR IP : le forum est une fonction de compte, et deux
        étudiants derrière le même NAT d'école n'ont pas à se gêner. La LECTURE
        n'y passe jamais -- un quota qui empêcherait de relire un fil
        empêcherait de suivre la réponse qu'on attend.
        """
        with self.lock:
            wait = self.forum_quota.check(sub, time.time())
        if wait:
            self._json(429, {"error": "trop de messages d'un coup -- réessaie "
                                      f"dans {wait} s", "retry_after": wait})
        return bool(wait)

    def _forum_fil(self):
        """GET /forum?ex=<exercice> -- le fil, tel que cet appelant a le droit de
        le voir."""
        sub = self._forum_qui()
        if sub is None:
            return
        entry = self._forum_entree(self._param("ex"))
        if entry is None:
            return
        messages = etat.forum_fil(entry["id"], FORUM_MAX_FIL)
        if messages is None:
            self._json(503, {"error": "la base ne répond pas"})
            return
        moderateur = is_moderator(sub)
        self._json(200, {
            "exercice_id": entry["id"],
            "moderateur": moderateur,
            "max": FORUM_MAX_CHARS,
            "messages": forum_vue(messages, sub, moderateur),
        })

    def _forum_publier(self):
        """POST /forum -- publier dans le fil d'un exercice publié."""
        sub = self._forum_qui()
        if sub is None:
            return
        data = self._body()
        if data is None:
            return
        entry = self._forum_entree(data.get("tp"))
        if entry is None:
            return
        texte, message = forum_texte(data.get("texte"))
        if message:
            self._json(400, {"error": message})
            return
        if self._forum_throttle(sub):
            return
        if not etat.forum_publier(uuid.uuid4().hex, entry["id"], sub, texte):
            self._json(503, {"error": "la base ne répond pas"})
            return
        self._json(200, {"ok": True})

    def _forum_supprimer(self):
        """DELETE /forum?id=<message> -- supprimer SON message, jamais un autre.

        Le même 404 pour « ce message n'existe pas » et « il n'est pas à toi » :
        les distinguer dirait à qui essaie qu'un identifiant existe.
        """
        sub = self._forum_qui()
        if sub is None:
            return
        message_id = self._forum_message_id(self._param("id"))
        if message_id is None:
            return
        efface = etat.forum_supprimer(message_id, sub)
        if efface is None:
            self._json(503, {"error": "la base ne répond pas"})
        elif not efface:
            self._json(404, {"error": "message introuvable"})
        else:
            self._json(200, {"ok": True})

    def _forum_signaler(self):
        """POST /forum/signalement -- signaler un message.

        LA MÊME RÉPONSE pour un signalement neuf, un doublon et un identifiant
        inconnu : c'est déjà ce que la base impose (clé primaire, et un INSERT
        qui ne trouve pas son message n'insère rien), et l'étudiant n'a pas
        besoin d'apprendre lequel des trois cas s'applique. Il a signalé ;
        quelqu'un lira.
        """
        sub = self._forum_qui()
        if sub is None:
            return
        data = self._body()
        if data is None:
            return
        message_id = self._forum_message_id(data.get("id"))
        if message_id is None:
            return
        if self._forum_throttle(sub):
            return
        if etat.forum_signaler(message_id, sub) is None:
            self._json(503, {"error": "la base ne répond pas"})
            return
        self._json(200, {"ok": True})

    def _forum_file_moderation(self):
        """GET /forum/moderation -- les signalements. Réservé, contrôlé serveur."""
        if self._forum_moderateur() is None:
            return
        signales = etat.forum_signalements(FORUM_MAX_FIL)
        if signales is None:
            self._json(503, {"error": "la base ne répond pas"})
            return
        self._json(200, {"signalements": signales})

    def _forum_moderer(self):
        """POST /forum/moderation -- masquer ou rétablir UN message.

        Les deux seules actions possibles. Éditer ou réécrire un message n'en
        fait pas partie : un message est immuable, et un modérateur qui pourrait
        le corriger pourrait aussi faire dire autre chose à quelqu'un.
        """
        sub = self._forum_moderateur()
        if sub is None:
            return
        data = self._body()
        if data is None:
            return
        message_id = self._forum_message_id(data.get("id"))
        if message_id is None:
            return
        action = str(data.get("action", ""))
        if action not in ("masquer", "retablir"):
            self._json(400, {"error": "action inconnue"})
            return
        fait = etat.forum_moderer(uuid.uuid4().hex, message_id, sub, action)
        if fait is None:
            self._json(503, {"error": "la base ne répond pas"})
        elif not fait:
            self._json(404, {"error": "message introuvable"})
        else:
            self._json(200, {"ok": True})

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
        path = self.path.split("?", 1)[0]
        if path == "/forum":
            self._forum_supprimer()
            return
        if path != "/moi":
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

    def _detail(self, tp):
        """La consigne et les gabarits d'un exercice, publiés par le worker.

        Même porte que `_quiz` : `find_tp` refuse ce qui n'est pas un TP du
        catalogue, donc `/tp/../tps.json` n'est pas un chemin à traverser mais
        un identifiant qui n'existe pas.
        """
        entry = find_tp(tp)
        if entry is None:
            self._json(404, {"error": "inconnu"})
            return
        self._file(os.path.join("tp", entry["id"] + ".json"),
                   "application/json; charset=utf-8")

    def _result(self, job_id):
        if not JOB_RE.match(job_id):
            self._json(400, {"error": "identifiant invalide"})
            return
        tp, owner = job_metadata(job_id)
        path = os.path.join(SPOOL, job_id, "result.json")
        try:
            with open(path, encoding="utf-8") as fh:
                result = json.load(fh)
                if owner is not None and tp and isinstance(result, dict):
                    # A database outage must never hide a verdict or stop the
                    # anonymous core of ctester.  The unique job_id makes every
                    # later poll retry this write safely.
                    etat.write_practice_attempt(owner, job_id, tp, result)
                    entry = find_tp(tp)
                    if entry is not None:
                        solved = (result.get("status") == "ok"
                                  and result.get("total", 0) > 0
                                  and result.get("passed") == result.get("total"))
                        # `write_state` never moves `valide` backwards.  This
                        # replaces the old browser-declared state transition.
                        etat.write_state(owner, tp,
                                         "valide" if solved else "essaye",
                                         job_sources(job_id, entry))
                        if solved:
                            recompenser(owner, entry, job_id)
                self._json(200, result)
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
        path = self.path.split("?", 1)[0]
        if path == "/forum":
            self._forum_publier()
            return
        if path == "/forum/signalement":
            self._forum_signaler()
            return
        if path == "/forum/moderation":
            self._forum_moderer()
            return
        if path != "/submit":
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
            self._corps_lu = True
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
            # Connection is optional.  A valid signed-in student gets a server
            # owned practice record; everyone else keeps the anonymous flow.
            job_id = self._spool(tp, name, blob, current_user(self.headers))

        self._json(200, {"id": job_id})

    def _spool(self, tp, name, blob, owner=None):
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
            job = {"tp": tp}
            if isinstance(owner, str) and 0 < len(owner) <= 128:
                job["owner"] = owner
            json.dump(job, fh)
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
    # Le forum est ETEINT tant qu'aucun moderateur n'est configure, et il le
    # dit : « personne ne clique dessus » et « il n'existe pas » se ressemblent
    # trop de l'exterieur pour qu'on laisse deviner lequel des deux.
    if oidc_enabled() and not FORUM_MODERATORS:
        print("discussions desactivees : CTESTER_FORUM_MODERATORS est vide"
              " (liste de `sub` OIDC separes par des virgules)", file=sys.stderr)
    os.makedirs(SPOOL, exist_ok=True)
    ThreadingHTTPServer(("", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
