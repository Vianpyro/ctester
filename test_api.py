#!/usr/bin/env python3
"""La frontière HTTP de l'API FastAPI, éprouvée par `fastapi.testclient`.

Ce qui se voit depuis un navigateur -- codes, en-têtes, formes de corps -- et surtout
LES BORNES. Les règles pures (progression, forum, catalogue) restent éprouvées
par appel direct dans `test_ctester.py`, sans serveur.

    python3 test_api.py

UNE dépendance de test, `httpx2` (`pip install -r requirements-dev.txt`), tirée
par `TestClient`. L'APPLICATION, elle, n'a que ce que liste `requirements.txt`.

CE FICHIER TESTE LES EXTRÊMES, PAS LE CHEMIN HEUREUX. Chaque borne y est
éprouvée des DEUX CÔTÉS -- la valeur qui passe et la première qui ne passe plus.
Un test qui ne vérifie qu'un refus laisse passer une borne posée un cran trop
serré, et c'est l'étudiant qui la découvre à 23 h la veille de la remise.
"""

import contextlib
import io
import json
import pathlib
import re
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "app")]

# AVANT D'IMPORTER `main` : `config` lit l'environnement à l'import.
os.environ.setdefault("CTESTER_ORIGINS",
                      "https://tch009.thevhome.com,https://vianpyro.github.io")

try:
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover -- message, pas trace
    sys.exit("test_api.py a besoin de httpx2 : pip install -r requirements-dev.txt")

import config      # noqa: E402
import deps        # noqa: E402
import state        # noqa: E402
import main        # noqa: E402
import security    # noqa: E402
import policy as politique  # noqa: E402
from services import quotas  # noqa: E402

CONNUE = "https://tch009.thevhome.com"
INCONNUE = "https://mechant.example"

client = TestClient(main.app)


# --- Harnais ----------------------------------------------------------------

def _modules_avec_etat():
    """Tous les modules qui ont importé `state`, pour le remplacer PARTOUT.

    `security`, `services.forum`, `services.progress` et quatre routeurs
    importent `state` chacun de leur côté. En oublier un ferait
    parler un test à une VRAIE base -- absente en test, donc `enabled()` faux,
    donc des 503 partout et un contrôle qui « passe » sans rien avoir éprouvé.

    Le balayage est dynamique exprès : un module ajouté demain est couvert sans
    que personne n'ait à penser à cette liste.
    """
    return [m for m in list(sys.modules.values())
            if getattr(m, "state", None) is state]


class BaseSimulee:
    """Une base en mémoire. Chaque méthode rend ce que `state.py` promet.

    `None` VEUT DIRE « LA BASE N'A PAS RÉPONDU », et c'est la moitié la plus
    importante du contrat : les routes doivent alors répondre 503, jamais 200
    avec un zéro. Les tests de panne remplacent une méthode par `lambda *_: None`.
    """

    STATUSES = ("attempted", "solved")
    THEMES = ("light", "dark")
    enabled = staticmethod(lambda: True)

    EMPTY_PROFILE = {"display_name": None, "group_number": None,
                   "display_name_public": False, "group_number_public": False,
                   "alias": None, "plate_frame": None,
                   "badges_public": False, "leaderboard_opt_in": False}

    def __init__(self):
        self.brouillons, self.etats, self.themes = {}, {}, {}
        self.messages, self.profils = [], {}
        self.pratique, self.jobs = {}, set()
        self.evenements, self.xp, self.succes = {}, {}, {}
        self.faits = []          # le journal, dans l'ordre d'écriture
        self.utiles = set()      # (message, account) -- "ça m'a aidé"
        self.retenus = {}        # message -> retained by a moderator?

    # -- comptes
    def read_resume(self, user, ex):
        return self.brouillons.get((user, ex))

    def write_draft(self, user, ex, sources):
        self.brouillons[(user, ex)] = sources
        return True

    def read_states(self, user):
        return [{"exercise_id": ex, "status": s}
                for (u, ex), s in self.etats.items() if u == user]

    def write_state(self, user, ex, status, sources):
        self.etats[(user, ex)] = status
        return True

    def read_theme(self, user):
        return self.themes.get(user, "")

    def write_theme(self, user, theme):
        self.themes[user] = theme
        return True

    def forget(self, user):
        for table in (self.brouillons, self.etats, self.themes, self.profils):
            for cle in [k for k in table if (k[0] if isinstance(k, tuple) else k) == user]:
                del table[cle]
        self.messages = [m for m in self.messages if m["account"] != user]
        return True

    # -- pratique et progression
    def read_practice_summary(self, user):
        return [{"exercise_id": ex, "attempts": n, "successes": r}
                for (u, ex), (n, r) in self.pratique.items() if u == user]

    def write_practice_attempt(self, user, job_id, ex, result):
        if job_id not in self.jobs:
            self.jobs.add(job_id)
            n, r = self.pratique.get((user, ex), (0, 0))
            gagne = (result.get("total", 0) > 0
                     and result.get("passed") == result.get("total"))
            self.pratique[(user, ex)] = (n + 1, r + int(gagne))
        return True

    def grant_first_solve(self, user, ex, event_id, amount, reason, policy,
                          payload, daily_cap):
        # LA CLÉ EST LE FAIT, pas l'appel : rejouer le même verdict retombe sur
        # la même clé et ne crée rien.
        if (user, event_id) in self.evenements:
            return None
        self.evenements[(user, event_id)] = payload
        self.faits.append({"account": user, "type": "ExerciceReussi",
                           "exercise_id": ex, "payload": payload})
        deja = sum(t["amount"] for (u, _), t in self.xp.items() if u == user)
        self.xp[(user, event_id)] = {
            "exercise_id": ex, "amount": max(min(amount, daily_cap - deja), 0),
            "reason": reason, "granted_at": "2026-09-04"}
        return self.xp[(user, event_id)]["amount"]

    def record_event(self, user, event_id, kind, ex, policy, payload):
        # Même clé, même refus que `grant_first_solve` : un sondage rejoué
        # n'ajoute pas une évidence de plus.
        if (user, event_id) in self.evenements:
            return None
        self.evenements[(user, event_id)] = payload
        self.faits.append({"account": user, "type": kind,
                           "exercise_id": ex, "payload": payload})
        return event_id

    def read_events(self, user, kind, limit=500):
        return [{"exercise_id": fait["exercise_id"], "payload": fait["payload"]}
                for fait in reversed(self.faits)
                if fait["account"] == user and fait["type"] == kind][:limit]

    def unlock(self, user, ids, event_id, policy):
        for succes_id in ids:
            self.succes.setdefault((user, succes_id),
                                   {"id": succes_id, "unlocked_at": "2026-09-04",
                                    "policy": policy})
        return True

    def read_practice_days(self, user, days):
        # Un seul jour, celui de tout ce harnais : ce qu'on eprouve ici est que
        # la route porte le calendrier, pas que Postgres sache grouper.
        n = sum(a for (u, _), (a, _) in self.pratique.items() if u == user)
        return [{"date": "2026-09-04", "attempts": n}] if n else []

    def read_unlock_rates(self):
        compte = {}
        for (_, succes_id) in self.succes:
            compte[succes_id] = compte.get(succes_id, 0) + 1
        return compte, len({u for (u, _) in self.pratique})

    def leaderboard_rows(self, group_number, days):
        rows = []
        for compte, profil in self.profils.items():
            if not profil.get("leaderboard_opt_in"):
                continue
            if group_number is not None and profil.get("group_number") != group_number:
                continue
            n = sum(1 for (u, _) in self.xp if u == compte)
            rows.append({"account": compte, "alias": profil.get("alias"),
                         "group_number": profil.get("group_number"),
                         "recent": n, "lifetime": n})
        return rows

    def forum_taken_aliases(self):
        return {p["alias"] for p in self.profils.values() if p.get("alias")}

    def read_progress(self, user):
        mien = lambda t: [v for (u, _), v in sorted(t.items()) if u == user]  # noqa: E731
        return {"xp": sum(t["amount"] for t in mien(self.xp)),
                "achievements": mien(self.succes), "transactions": mien(self.xp)}

    # -- forum
    def forum_fil(self, ex, limite, reader=None):
        views = []
        for m in self.messages:
            if m["exercise_id"] != ex:
                continue
            views.append(dict(m, retained=self.retenus.get(m["id"], False),
                              helpful=sum(1 for (i, _) in self.utiles if i == m["id"]),
                              helped_me=(m["id"], reader or "") in self.utiles))
        return views[:limite]

    def forum_publier(self, mid, ex, user, texte, step=None, blocked_kind=None,
                      visibility="thread"):
        self.messages.append({"id": mid, "exercise_id": ex, "account": user,
                              "text": texte, "hidden": False,
                              "step": step, "blocked_kind": blocked_kind,
                              "visibility": visibility,
                              "created_at": "2026-09-04"})
        return True

    def forum_open_to_group(self, mid, user):
        # THE SAME RULE AS THE SQL `WHERE`: one's own, and private only.
        for m in self.messages:
            if (m["id"] == mid and m["account"] == user
                    and m.get("visibility") == "private"):
                m["visibility"] = "group"
                return [mid]
        return []

    def forum_mark_helpful(self, mid, user):
        for m in self.messages:
            if m["id"] == mid and m["account"] != user:
                if (mid, user) in self.utiles:
                    return []
                self.utiles.add((mid, user))
                return [mid]
        return []

    def forum_help_rows(self, limit, hours):
        groups = {}
        for m in self.messages:
            if not m.get("step") or m["hidden"]:
                continue
            key = (m["exercise_id"], m["step"], m.get("blocked_kind"))
            row = groups.setdefault(key, {"exercise_id": key[0], "step": key[1],
                                          "blocked_kind": key[2], "people": 0,
                                          "opened": 0, "since": m["created_at"],
                                          "accounts": set()})
            row["accounts"].add(m["account"])
            row["people"] = len(row["accounts"])
            row["opened"] += int(m.get("visibility") == "group")
        rows = [{k: v for k, v in row.items() if k != "accounts"}
               for row in groups.values()]
        return sorted(rows, key=lambda row: -row["people"])[:limit]

    def forum_supprimer(self, mid, user):
        avant = len(self.messages)
        self.messages = [m for m in self.messages
                         if not (m["id"] == mid and m["account"] == user)]
        return len(self.messages) < avant

    def forum_signaler(self, mid, user):
        return True

    def forum_nom_signaler(self, mid, user):
        return True

    def forum_signalements(self, limite):
        return []

    def forum_noms_signales(self, limite):
        return []

    def forum_moderer(self, aid, mid, moderateur, action):
        for m in self.messages:
            if m["id"] == mid:
                # RETAINING EDITS NOTHING: the message stays identical, only
                # the mark moves -- like the journal in the real database.
                if action in ("retain", "unretain"):
                    self.retenus[mid] = (action == "retain")
                else:
                    m["hidden"] = (action == "hide")
                return True
        return False

    def forum_auteur(self, mid):
        for m in self.messages:
            if m["id"] == mid:
                return m["account"]
        return None

    def forum_profil(self, user):
        return self.profils.get(user, dict(self.EMPTY_PROFILE))

    def forum_profils(self, users):
        return {u: self.profils[u] for u in users if u in self.profils}

    def forum_profil_ecrire(self, pid, user, pseudo, groupe, pseudo_public,
                            groupe_public, set_by_moderator=False, alias=None,
                            plate_frame=None, badges_public=False,
                            leaderboard_opt_in=False):
        # LA DERNIERE LIGNE EST LE PROFIL, comme en base : on remplace tout,
        # et c'est ce qui fait echouer une ecriture partielle ici aussi.
        self.profils[user] = {"display_name": pseudo, "group_number": groupe,
                              "display_name_public": pseudo_public,
                              "group_number_public": groupe_public,
                              "alias": alias, "plate_frame": plate_frame,
                              "badges_public": badges_public,
                              "leaderboard_opt_in": leaderboard_opt_in}
        return True


# LE CONTENU DU DÉPLOIEMENT DE TEST, DANS SA FORME PRIVÉE. Le catalogue servi
# en est TIRÉ par `publish_content`, exactement comme en production : écrire un
# `catalog.json` à la main ici éprouverait une forme que rien ne produit.
#
# Un exercice par mode, parce que c'est le mode qui décide de ce que l'API
# attend -- des fichiers, un module à deux fichiers, ou des réponses.
CONTENU = [
    ("tp2-ex3", "TP2 ex.3", "io", ["submission.c"], ["variables"], "foundation"),
    ("tp5-mod", "TP5 module", "unity", ["calendrier.h", "calendrier.c"],
     ["structs"], "intermediate"),
    ("quiz1", "Quiz 1", "quiz", [], ["variables"], "intro"),
    # UNE VÉRIFICATION, marquée par son identifiant dans ce harnais seulement
    # (voir `_ecrire_contenu`). Elle est ici pour que TOUTE la suite traverse
    # la branche : un catalogue de test sans vérification laisserait la phase 2
    # éprouvée uniquement par les trois tests qui la visent.
    ("verif-tp2", "Vérification TP2", "quiz", [], ["variables"], "foundation"),
]


def _ecrire_contenu(racine, exercices=CONTENU, release=None):
    """Une racine de contenu privé v2, prête pour `discover()`."""
    def ecrire(chemin, valeur):
        os.makedirs(os.path.dirname(chemin), exist_ok=True)
        with open(chemin, "w", encoding="utf-8") as fh:
            json.dump(valeur, fh)

    competences = sorted({c for _, _, _, _, skills, _ in exercices for c in skills})
    ecrire(os.path.join(racine, "catalog.json"),
           {"schema_version": 1, "skills": competences})
    for identifiant, titre, mode, fichiers, skills, difficulte in exercices:
        dossier = os.path.join(racine, "exercises", identifiant)
        ecrire(os.path.join(dossier, "exercise.json"),
               {"schema_version": 1, "id": identifiant, "title": titre,
                "skills": skills, "difficulty": difficulte,
                "verification": identifiant.startswith("verif-"),
                "release": release or {"state": "available"}})
        with open(os.path.join(dossier, "statement.md"), "w", encoding="utf-8") as fh:
            fh.write("Consigne.")
        assessment = os.path.join(dossier, "assessment")
        if mode == "io":
            ecrire(os.path.join(assessment, "io.json"),
                   {"cases": [{"stdin": "1\n", "expect": [1]}]})
        elif mode == "unity":
            ecrire(os.path.join(assessment, "unity.json"), {})
            with open(os.path.join(assessment, "test_x.c"), "w",
                      encoding="utf-8") as fh:
                fh.write("void test_x(void) {}\n")
        else:
            ecrire(os.path.join(assessment, "quiz.json"),
                   {"questions": [{"id": "q1", "type": "int", "text": "2+2 ?",
                                   "answer": 4}]})
        if fichiers:
            ecrire(os.path.join(dossier, "public", "files.json"),
                   {"files": [{"name": nom, "template": ""} for nom in fichiers]})


def _publier(tmp, exercices=CONTENU):
    """Publie ce contenu et pose le pointeur. Rend le répertoire des releases."""
    import content_catalog as content_catalogue
    import publish_content
    racine = os.path.join(tmp, "content")
    publie = os.path.join(tmp, "published")
    _ecrire_contenu(racine, exercices)
    publish_content.publish(content_catalogue.discover(racine), publie)
    return publie


@contextlib.contextmanager
def contexte(*, jetons=None, moderateurs=(), forum_actif=True, base=None,
             groupes=(4, 6)):
    """Un déploiement complet en mémoire, remis en place à la sortie.

    TOUT EST RESTAURÉ DANS UN `finally`, y compris les quotas : un test qui
    laisserait un compteur rempli ferait échouer le SUIVANT, et on chercherait
    le bug dans le mauvais fichier.
    """
    tmp = tempfile.mkdtemp()
    spool, page = (os.path.join(tmp, n) for n in ("spool", "web"))
    for chemin in (spool, page):
        os.makedirs(chemin)
    publie = _publier(tmp)

    faux = base if base is not None else BaseSimulee()
    modules = _modules_avec_etat()
    garde_etat = [(m, m.state) for m in modules]
    garde_config = {n: getattr(config, n) for n in
                    ("PUBLISHED", "SPOOL", "PAGE", "KEY", "OIDC_ISSUER",
                     "OIDC_CLIENT_ID", "FORUM_MODERATORS", "FORUM_GROUPES")}
    garde_secu = (security.current_user, security.current_name)
    garde_quotas = (deps.quota, deps.quota_connecte, deps.state_quota,
                    deps.forum_quota, deps.presence)

    for m in modules:
        m.state = faux
    config.SPOOL, config.PAGE = spool, page
    # LA RELEASE DE CE DÉPLOIEMENT, pas celle de la machine qui lance les tests :
    # un `CTESTER_PUBLISHED` exporté dans un shell ne doit pas décider de ce
    # qu'ils éprouvent.
    config.PUBLISHED = publie
    config.KEY = "cle-de-session"
    config.OIDC_ISSUER = "https://auth.exemple.com"
    config.OIDC_CLIENT_ID = "ctester"
    config.FORUM_MODERATORS = frozenset(moderateurs) if forum_actif else frozenset()
    config.FORUM_GROUPES = tuple(groupes)
    jetons = jetons or {}
    security.current_user = lambda entetes: jetons.get(
        entetes.get("Authorization", "").replace("Bearer ", ""))
    security.current_name = lambda entetes: ""
    # Des quotas neufs et larges : ces contrôles éprouvent des bornes précises,
    # et ceux qui éprouvent un quota posent le leur.
    deps.quota = quotas.Quota(cooldown=0, hourly=100000)
    deps.quota_connecte = quotas.Quota(cooldown=0, hourly=100000)
    deps.state_quota = quotas.Quota(cooldown=0, hourly=100000)
    deps.forum_quota = quotas.Quota(cooldown=0, hourly=100000)
    deps.presence = quotas.Presence()

    try:
        yield TestClient(main.create_app()), faux, tmp
    finally:
        for m, ancien in garde_etat:
            m.state = ancien
        for nom, valeur in garde_config.items():
            setattr(config, nom, valeur)
        security.current_user, security.current_name = garde_secu
        (deps.quota, deps.quota_connecte, deps.state_quota, deps.forum_quota,
         deps.presence) = garde_quotas
        shutil.rmtree(tmp, ignore_errors=True)


def _contenu_v2(racine):
    """Une racine de contenu v2 : un exercice ouvert, un exercice programmé."""
    def ecrire(chemin, valeur):
        os.makedirs(os.path.dirname(chemin), exist_ok=True)
        with open(chemin, "w", encoding="utf-8") as fh:
            json.dump(valeur, fh)

    ecrire(os.path.join(racine, "catalog.json"), {"schema_version": 1, "skills": []})
    for identifiant, release in (("ouvert", {"state": "available"}),
                                 ("ferme", {"state": "scheduled",
                                            "available_from": "2099-01-01T00:00:00-05:00"})):
        exercice = os.path.join(racine, "exercises", identifiant)
        ecrire(os.path.join(exercice, "exercise.json"),
               {"schema_version": 1, "id": identifiant, "title": identifiant.title(),
                "release": release})
        with open(os.path.join(exercice, "statement.md"), "w", encoding="utf-8") as fh:
            fh.write("Consigne.")
        ecrire(os.path.join(exercice, "assessment", "io.json"),
               {"cases": [{"stdin": "1\\n", "expect": [1]}]})
        ecrire(os.path.join(exercice, "public", "files.json"),
               {"files": [{"name": "submission.c", "template": ""}]})
    ecrire(os.path.join(racine, "collections", "tp1.json"),
           {"schema_version": 1, "id": "tp1", "title": "TP 1",
            "items": ["ouvert", "ferme"], "release": {"state": "available"}})


def test_release_pilote_le_catalogue_et_ferme_le_reste():
    """Le catalogue vient de la release, et le cadenas tient partout.

    LES DEUX MOITIÉS COMPTENT. Un exercice programmé est VISIBLE dans
    `/catalog.json` (avec son état) et reste injoignable partout ailleurs :
    ni consigne, ni soumission. Montrer n'est pas donner, et l'inverse --
    le faire disparaître, comme en v1 -- ressemblait à une panne.

    ET SANS RELEASE, RIEN. Depuis la phase 8 il n'y a plus de repli `tps.json` :
    un pointeur absent est un catalogue absent, ce que la page dit au lieu
    d'afficher un menu vide.
    """
    import content_catalog as content_catalogue
    import publish_content

    with contexte() as (c, _, tmp):
        racine, publie = os.path.join(tmp, "v2"), os.path.join(tmp, "releases")
        _contenu_v2(racine)
        publish_content.publish(content_catalogue.discover(racine), publie)
        config.PUBLISHED = publie

        catalog = c.get("/catalog.json").json()
        etats = {e["id"]: e["access"] for e in catalog["exercises"]}
        assert etats == {"ouvert": "available", "ferme": "scheduled"}, etats
        assert catalog["collections"][0]["items"] == ["ouvert", "ferme"]

        assert c.get("/tp/ouvert.json").json()["statement"] == "Consigne."
        assert c.get("/tp/ferme.json").status_code == 404

        corps = {"key": config.KEY, "files": {"submission.c": "int main(void){}"}}
        assert c.post("/submit", json=dict(corps, exercise_id="ferme")).status_code == 400
        assert c.post("/submit", json=dict(corps, exercise_id="ouvert")).status_code == 200

        # PLUS DE POINTEUR : le catalogue est absent, et plus rien ne se résout.
        config.PUBLISHED = ""
        assert c.get("/catalog.json").status_code == 404
        assert c.get("/tp/ouvert.json").status_code == 404
        assert c.post("/submit", json=dict(corps, exercise_id="ouvert")).status_code == 400


def auth(nom):
    return {"Authorization": "Bearer " + nom}


# --- Transport : CORS, cache, préflight, 404 --------------------------------

def test_healthz_ne_touche_ni_base_ni_spool():
    """Le healthcheck du conteneur : vrai tant que ce processus sert du HTTP.

    S'il interrogeait Postgres, une panne de base ferait redémarrer en boucle le
    conteneur web -- alors que le parcours anonyme, lui, fonctionne encore.
    """
    r = client.get("/healthz")
    assert r.status_code == 200, r.status_code
    assert r.json() == {"ok": True}, r.json()


def test_cors_origine_connue_et_inconnue():
    """Une origine connue reçoit l'en-tête ; une inconnue ne reçoit RIEN.

    Pas de 403 : un réglage oublié ne doit pas ressembler à une panne de
    service, et le navigateur bloque de lui-même. Et jamais `*` -- chaque
    requête de compte porte un `Authorization`.
    """
    r = client.get("/healthz", headers={"Origin": CONNUE})
    assert r.headers.get("access-control-allow-origin") == CONNUE, dict(r.headers)

    r = client.get("/healthz", headers={"Origin": INCONNUE})
    assert r.status_code == 200, r.status_code
    assert "access-control-allow-origin" not in r.headers, dict(r.headers)

    # Aucun cookie ici : le jeton voyage en en-tête.
    assert "access-control-allow-credentials" not in r.headers

    # La barre oblique finale ne doit pas faire d'une origine connue une
    # inconnue : `config.ORIGINS` et l'en-tête reçu sont tous deux `rstrip`és.
    r = client.get("/healthz", headers={"Origin": CONNUE + "/"})
    assert r.headers.get("access-control-allow-origin") == CONNUE, dict(r.headers)


def test_un_seul_vary_annoncant_les_deux_axes():
    """Deux lignes `Vary` sont légales et mal recombinées par certains caches.

    Un cache qui perd `Origin` sert la réponse d'une origine à une autre.
    `httpx` joint les doublons par « , » : on compte donc les occurrences de
    chaque axe, pas la longueur de la chaîne.
    """
    r = client.get("/healthz", headers={"Origin": CONNUE})
    vary = r.headers.get("vary", "")
    assert vary == "Accept-Encoding, Origin", vary
    assert vary.count("Origin") == 1 and vary.count("Accept-Encoding") == 1, vary


def test_preflight_sur_toute_route_meme_inconnue():
    """204, et `DELETE` dans la liste -- `compte.js` et `forum.js` en dépendent.

    Le préflight ne passe pas par le routeur : il répond avant, donc un chemin
    qui n'existe pas encore répond quand même. `Max-Age` évite un aller-retour
    de plus par PUT et par DELETE.
    """
    for chemin in ("/submit", "/forum", "/pas-encore-invente"):
        r = client.options(chemin, headers={"Origin": CONNUE})
        assert r.status_code == 204, (chemin, r.status_code)
        methodes = r.headers.get("access-control-allow-methods", "")
        assert "DELETE" in methodes, methodes
        assert r.headers.get("access-control-max-age") == "86400", dict(r.headers)
        assert r.headers.get("access-control-allow-origin") == CONNUE

    r = client.options("/submit", headers={"Origin": INCONNUE})
    assert "access-control-allow-origin" not in r.headers, dict(r.headers)


def test_chemin_inconnu_reste_un_404():
    """Et pas un 405.

    Une route attrape-tout `OPTIONS /{chemin:path}` ferait répondre « méthode
    non autorisée » à tout chemin inexistant : Starlette retient sa
    correspondance partielle et ne descend jamais jusqu'au 404. C'est faux, et
    ça confirme au passage que le chemin existe.
    """
    r = client.get("/pas-une-route")
    assert r.status_code == 404, r.status_code
    assert r.json() == {"error": "inconnu"}, r.json()


def test_documentation_automatique_eteinte():
    """`/docs`, `/redoc` et `/openapi.json` décrivent toute la surface de l'API.

    FastAPI les sert publiquement par défaut. Sur une infra personnelle, c'est
    un plan des lieux offert. `config.DOCS` les retire -- la route n'existe pas,
    il n'y a donc rien à contourner.
    """
    assert not config.DOCS, "CTESTER_DOCS ne doit pas être posé en production"
    for chemin in ("/openapi.json", "/docs", "/redoc"):
        assert client.get(chemin).status_code == 404, chemin


def test_no_store_par_defaut_sur_les_donnees():
    """Le défaut est `no-store` ; seuls les fichiers disent `no-cache`."""
    assert client.get("/healthz").headers.get("cache-control") == "no-store"
    assert client.get("/rien").headers.get("cache-control") == "no-store"
    with contexte() as (c, _, _tmp):
        assert c.get("/catalog.json").headers.get("cache-control") == "no-cache"
        assert c.get("/oidc.json").headers.get("cache-control") == "no-store"


def test_pas_d_annonce_de_version_de_serveur():
    """`Server: uvicorn` ne sert que celui qui cherche une version vulnérable.

    Le contrôle porte sur le RÉGLAGE et pas sur la réponse : `TestClient` ne
    passe pas par uvicorn, donc l'en-tête n'apparaît qu'en vrai.
    """
    with open(os.path.join(HERE, "app", "main.py"), encoding="utf-8") as fh:
        source = fh.read()
    assert "server_header=False" in source
    assert "workers=1" in source


# --- Bornes du corps de requête ---------------------------------------------

def test_borne_du_corps_des_deux_cotes():
    """`MAX_CODE + 4096` passe, un octet de plus ne passe pas.

    Uvicorn N'A PAS de limite de taille de corps. Sans cette borne, un POST
    annonçant deux gigaoctets ferait lire deux gigaoctets avant la moindre
    validation. Le test porte sur le `Content-Length` ANNONCÉ : c'est lui qu'on
    refuse, avant de lire quoi que ce soit.
    """
    plafond = config.MAX_CODE + 4096
    with contexte() as (c, _, _tmp):
        # Pile sur la borne : accepté par le middleware (le 400 qui suit vient
        # de la validation, ce qui prouve justement qu'on est allé plus loin).
        corps = b'{"exercise_id": "tp2-ex3", "key": "x", "bourrage": "'
        corps += b"a" * (plafond - len(corps) - 2) + b'"}'
        assert len(corps) == plafond
        r = c.post("/submit", content=corps,
                   headers={"Content-Type": "application/json"})
        assert r.status_code != 413, (r.status_code, r.text)

        # Un octet de plus : refusé sans être lu.
        r = c.post("/submit", content=corps + b" ",
                   headers={"Content-Type": "application/json"})
        assert r.status_code == 413, r.status_code
        assert r.json() == {"error": "corps trop gros ou vide"}, r.json()


def test_corps_vide_ou_sans_longueur_annoncee():
    """Zéro octet et `Content-Length` absent sont tous deux refusés.

    Absent vaut « hors bornes » : une requête `chunked` n'annonce pas sa taille,
    et on ne lit pas un corps dont on ignore la longueur.
    """
    with contexte() as (c, _, _tmp):
        r = c.post("/submit", content=b"",
                   headers={"Content-Type": "application/json"})
        assert r.status_code == 413, (r.status_code, r.text)

        def flux():
            yield b'{"exercise_id": "tp2-ex3"}'

        r = c.post("/submit", content=flux(),
                   headers={"Content-Type": "application/json"})
        assert r.status_code == 413, (r.status_code, r.text)


def test_corps_malforme_ne_renvoie_pas_l_entree():
    """422 de Pydantic -> 400 `{"error": ...}`, sans recopier ce qui a été reçu.

    Le défaut de FastAPI renvoie la valeur refusée à l'expéditeur. La page n'y
    comprendrait rien (elle lit `out.error`), et un corps refusé peut contenir
    le code de quelqu'un ou un jeton mal collé.
    """
    with contexte() as (c, _, _tmp):
        secret = "MonMotDePasseColleParErreur"
        r = c.post("/submit", content=json.dumps([secret]).encode(),
                   headers={"Content-Type": "application/json"})
        assert r.status_code == 400, (r.status_code, r.text)
        assert r.json() == {"error": "requête malformée"}, r.json()
        assert secret not in r.text, r.text


# --- La clé de session ------------------------------------------------------

def test_cle_verifiee_avant_tout_autre_travail():
    """Une mauvaise clé répond 403 MÊME sur un TP inconnu.

    L'ordre est la propriété : si le catalogue était consulté d'abord, la
    différence entre « TP inconnu » (400) et « clé invalide » (403) dirait à qui
    sonde quels exercices existent, sans clé.
    """
    with contexte() as (c, _, _tmp):
        r = c.post("/submit", json={"key": "mauvaise", "exercise_id": "nexiste-pas"})
        assert r.status_code == 403, (r.status_code, r.text)
        r = c.post("/submit", json={"key": "cle-de-session", "exercise_id": "nexiste-pas"})
        assert r.status_code == 400, (r.status_code, r.text)


def test_cle_vide_du_serveur_refuse_tout():
    """`CTESTER_KEY` vide n'ouvre pas la porte à une clé vide.

    Sans le premier `if`, `compare_digest("", "")` est vrai : un déploiement qui
    a perdu sa variable d'environnement servirait tout le monde.
    """
    with contexte() as (c, _, _tmp):
        config.KEY = ""
        r = c.post("/submit", json={"key": "", "exercise_id": "tp2-ex3",
                                    "files": {"submission.c": "int main(){}"}})
        assert r.status_code == 403, (r.status_code, r.text)


# --- Bornes du catalogue et des fichiers ------------------------------------

def test_taille_des_fichiers_des_deux_cotes():
    """Exactement `MAX_CODE` passe, un octet de plus rend 413.

    La borne porte sur le JSON des fichiers, pas sur le corps de la requête :
    les deux existent, et c'est celle-ci qui protège la base et le spool.
    """
    with contexte() as (c, _, _tmp):
        from services import catalog as catalogue
        entree = catalogue.find_exercise("tp2-ex3")
        enveloppe = len(json.dumps({"submission.c": ""}).encode())
        pile = "a" * (config.MAX_CODE - enveloppe)
        fichiers, message, code = catalogue.validate_files(
            entree, {"submission.c": pile})
        assert message is None, message
        assert len(json.dumps(fichiers).encode()) == config.MAX_CODE

        _, message, code = catalogue.validate_files(
            entree, {"submission.c": pile + "a"})
        assert code == 413 and message, (code, message)

        # `sent` hors-forme : Pydantic bloque déjà ceci à la frontière HTTP
        # (`files: dict`), mais la fonction reste appelable directement par le
        # brouillon comme par la soumission, et doit refuser proprement.
        _, message, code = catalogue.validate_files(entree, ["pas", "un", "dict"])
        assert code == 400 and message == "fichiers manquants", (code, message)


def test_fichier_inattendu_est_refuse_pas_ignore():
    """Un nom hors catalogue est REFUSÉ, pas silencieusement jeté.

    Un étudiant doit savoir que son fichier n'a pas été pris. Le laisser tomber
    en silence produit un verdict sur un module incomplet, que personne ne
    comprend.
    """
    with contexte() as (c, _, _tmp):
        r = c.post("/submit", json={
            "key": "cle-de-session", "exercise_id": "tp5-mod",
            "files": {"calendrier.h": "x", "calendrier.c": "y",
                      "secret.c": "z"}})
        assert r.status_code == 400, (r.status_code, r.text)
        assert "secret.c" in r.json()["error"], r.json()


def test_soumission_entierement_blanche_est_refusee():
    """Espaces et retours à la ligne ne sont pas du code.

    Sans ça, cliquer « Tester » sur un éditeur vide occuperait un cœur du Dell
    pour compiler du vide.
    """
    with contexte() as (c, _, _tmp):
        r = c.post("/submit", json={"key": "cle-de-session", "exercise_id": "tp2-ex3",
                                    "files": {"submission.c": "   \n\t  "}})
        assert r.status_code == 400, (r.status_code, r.text)
        assert r.json()["error"] == "soumission vide", r.json()


def test_quiz_bornes_du_nombre_et_de_la_longueur_des_reponses():
    """500 réponses gardées, la 501e jetée ; clés et valeurs coupées à 64.

    `Content-Length` ne suffit pas : un dictionnaire de dix mille clés d'une
    lettre tient largement sous la borne de corps.
    """
    with contexte() as (c, _, tmp):
        reponses = {"q%d" % i: "x" for i in range(600)}
        reponses["k" * 100] = "v" * 100
        r = c.post("/submit", json={"key": "cle-de-session", "exercise_id": "quiz1",
                                    "answers": reponses})
        assert r.status_code == 200, (r.status_code, r.text)
        job = r.json()["id"]
        with open(os.path.join(config.SPOOL, job, "answers.json"),
                  encoding="utf-8") as fh:
            ecrit = json.load(fh)
        assert len(ecrit) <= 500, len(ecrit)
        assert all(len(k) <= 64 and len(v) <= 64 for k, v in ecrit.items())


def test_quiz_sans_aucune_reponse_saisie():
    """Un quiz de 40 cases vides ne part pas dans la file."""
    with contexte() as (c, _, _tmp):
        r = c.post("/submit", json={"key": "cle-de-session", "exercise_id": "quiz1",
                                    "answers": {"q1": "  ", "q2": ""}})
        assert r.status_code == 400, (r.status_code, r.text)
        r = c.post("/submit", json={"key": "cle-de-session", "exercise_id": "quiz1",
                                    "answers": {}})
        assert r.status_code == 400, (r.status_code, r.text)
        # `answers` complètement absent (ou `null`) : refusé plus tôt, avant
        # même de regarder si une case porte quelque chose.
        r = c.post("/submit", json={"key": "cle-de-session", "exercise_id": "quiz1"})
        assert r.status_code == 400 and r.json() == {"error": "réponses manquantes"}, r.text


def test_identifiant_d_exercice_hors_forme():
    """Un chemin n'est pas un identifiant, et il ne le devient jamais.

    `find_exercise` COMPARE À L'IDENTIFIANT DU CATALOGUE, il ne le concatène
    pas : c'est ce qui fait que `/tp/../catalog.json` n'est pas un chemin à
    traverser mais un nom qui n'existe pas. Le chemin lu, lui, est reconstruit
    par `source_publiee` depuis l'entrée trouvée -- jamais depuis l'URL.
    """
    from services import catalog as catalogue
    with contexte() as (c, _, _tmp):
        assert catalogue.find_exercise("a" * 32) is None  # bien formé, mais absent
        for hostile in ("../tps", "tp2/../../etc", "TP2-EX3", "tp2 ex3", ""):
            assert catalogue.find_exercise(hostile) is None, hostile
        assert c.get("/tp/..%2Fcatalog.json").status_code == 404
        assert c.get("/quiz/tp2-ex3.json").status_code == 404  # pas un quiz
        # L'entrée trouvée, elle, donne un chemin sous la release et rien d'autre.
        base, nom = catalogue.source_publiee(
            catalogue.find_exercise("tp2-ex3"), "detail")
        assert base == catalogue.release_dir()
        assert nom == os.path.join("exercises", "tp2-ex3.json"), nom


# --- Bornes des quotas et de la file ----------------------------------------

def test_quota_horaire_pile_et_un_de_trop():
    """Le Nième passe, le N+1e rend 429 avec `retry_after`.

    Le `retry_after` est ce que la page affiche : sans lui, elle inviterait à
    recliquer tout de suite, ce qui rallongerait l'attente de tout le monde.
    """
    with contexte() as (c, _, _tmp):
        deps.quota = quotas.Quota(cooldown=0, hourly=3)
        charge = {"key": "cle-de-session", "exercise_id": "tp2-ex3",
                  "files": {"submission.c": "int main(){return 0;}"}}
        for i in range(3):
            assert c.post("/submit", json=charge).status_code == 200, i
        r = c.post("/submit", json=charge)
        assert r.status_code == 429, (r.status_code, r.text)
        assert r.json()["retry_after"] > 0, r.json()


def test_quota_par_compte_pas_par_ip_derriere_un_nat():
    """Deux comptes derrière UNE SEULE IP ne partagent pas le quota.

    C'est le cas du labo : 27 postes sortent par la même IP NATée, et compter
    par IP y ferait qu'un seul étudiant bloque toute la salle. L'anonyme, lui,
    reste compté par IP -- il n'a rien d'autre.
    """
    with contexte(jetons={"alice": "sub-alice", "bob": "sub-bob"}) as (c, _, _tmp):
        deps.quota = quotas.Quota(cooldown=0, hourly=1)
        deps.quota_connecte = quotas.Quota(cooldown=0, hourly=1)
        charge = {"key": "cle-de-session", "exercise_id": "tp2-ex3",
                  "files": {"submission.c": "int main(){return 0;}"}}
        nat = {"CF-Connecting-IP": "10.0.0.1"}
        for nom in ("alice", "bob"):
            r = c.post("/submit", json=charge, headers={**auth(nom), **nat})
            assert r.status_code == 200, (nom, r.status_code, r.text)
        # Chacun épuise le SIEN, et seulement le sien.
        r = c.post("/submit", json=charge, headers={**auth("alice"), **nat})
        assert r.status_code == 429, r.status_code
        # L'anonyme de la même salle garde son compteur d'IP, intact.
        assert c.post("/submit", json=charge, headers=nat).status_code == 200


def test_quota_anonyme_par_poste_et_cadran_plus_court_connecte():
    """Aux premiers labos personne n'est connecté, et la salle partage une IP.

    Deux postes anonymes derrière la MÊME IP ont chacun leur compteur ; sans
    jeton de poste, on retombe sur l'ancien comportement (l'IP seule). Et un
    compte attend moins entre deux soumissions -- son étiquette de quota est
    plus juste, donc moins facile à rejouer.
    """
    with contexte(jetons={"alice": "sub-alice"}) as (c, _, _tmp):
        deps.quota = quotas.Quota(cooldown=30, hourly=100)
        deps.quota_connecte = quotas.Quota(cooldown=0, hourly=100)
        charge = {"key": "cle-de-session", "exercise_id": "tp2-ex3",
                  "files": {"submission.c": "int main(){return 0;}"}}
        nat = {"CF-Connecting-IP": "10.0.0.1"}
        for poste in ("p1", "p2"):
            r = c.post("/submit?poste=" + poste, json=charge, headers=nat)
            assert r.status_code == 200, (poste, r.status_code, r.text)
        # Chaque poste épuise le sien, et seulement le sien.
        assert c.post("/submit?poste=p1", json=charge, headers=nat).status_code == 429
        assert c.post("/submit?poste=p3", json=charge, headers=nat).status_code == 200
        # Sans jeton : le compteur d'IP, comme avant. Deux d'affilée, la
        # seconde attend.
        assert c.post("/submit", json=charge, headers=nat).status_code == 200
        assert c.post("/submit", json=charge, headers=nat).status_code == 429
        # Le compte a son propre cadran, et le poste ne le concerne pas.
        for _ in range(3):
            r = c.post("/submit?poste=p1", json=charge,
                       headers={**auth("alice"), **nat})
            assert r.status_code == 200, (r.status_code, r.text)


def test_quota_ne_consomme_rien_sur_une_requete_refusee():
    """Un TP inconnu ne doit pas grignoter le quota de quelqu'un.

    Sinon un client bogué qui envoie un mauvais identifiant épuise le quota d'un
    étudiant qui n'a rien demandé, et c'est LUI qui reçoit le 429.
    """
    with contexte(jetons={"alice": "sub-alice"}) as (c, _, _tmp):
        deps.state_quota = quotas.Quota(cooldown=0, hourly=2)
        for _ in range(5):
            r = c.put("/brouillon", json={"exercise_id": "inconnu", "files": {}},
                      headers=auth("alice"))
            assert r.status_code == 400, r.status_code
        # Le quota est intact : les deux écritures valides passent encore.
        for _ in range(2):
            r = c.put("/brouillon",
                      json={"exercise_id": "tp2-ex3", "files": {"submission.c": "x"}},
                      headers=auth("alice"))
            assert r.status_code == 200, (r.status_code, r.text)
        r = c.put("/brouillon",
                  json={"exercise_id": "tp2-ex3", "files": {"submission.c": "x"}},
                  headers=auth("alice"))
        assert r.status_code == 429, (r.status_code, r.text)


def test_file_pleine_pile_sur_le_plafond():
    """`QUEUE_MAX` jobs en attente : le suivant rend 503, pas 200.

    Le plafond existe pour que la file reste lisible et que le Dell garde ses
    cœurs. Un job de plus accepté « juste cette fois » est ce qui fait déborder.
    """
    with contexte() as (c, _, _tmp):
        garde = config.QUEUE_MAX
        try:
            config.QUEUE_MAX = 2
            charge = {"key": "cle-de-session", "exercise_id": "tp2-ex3",
                      "files": {"submission.c": "int main(){}"}}
            assert c.post("/submit", json=charge).status_code == 200
            assert c.post("/submit", json=charge).status_code == 200
            r = c.post("/submit", json=charge)
            assert r.status_code == 503, (r.status_code, r.text)
        finally:
            config.QUEUE_MAX = garde


def test_presence_expire_pile_au_ttl():
    """Une fenêtre vue il y a exactement TTL secondes ne compte plus.

    Le TTL vaut 2,5 battements pour qu'un ping raté ne fasse pas clignoter le
    total. La borne est stricte (`>`), donc « pile au TTL » est expiré.
    """
    p = quotas.Presence()
    assert p.touch("a", 1000.0) == 1
    assert p.touch("a", 1000.0) == 1, "le même jeton ne compte pas deux fois"
    assert p.touch("b", 1000.0) == 2
    # `a` et `b` ont exactement TTL secondes : tous deux expirés, seul `c` reste.
    assert p.touch("c", 1000.0 + config.PRESENCE_TTL) == 1
    # Une seconde plus tôt, ils tiennent encore.
    q = quotas.Presence()
    q.touch("a", 1000.0)
    assert q.touch("c", 1000.0 + config.PRESENCE_TTL - 1) == 2


def test_live_tronque_un_jeton_trop_long_au_lieu_de_refuser():
    """La seule route anonyme ne doit jamais pouvoir échouer sur une entrée.

    Un `max_length` ferait un 400 sur un jeton fabriqué. Ce n'est qu'un chiffre
    affiché : il se tronque, il ne se plaint pas.
    """
    with contexte() as (c, _, _tmp):
        r = c.get("/live?id=" + "z" * 500)
        assert r.status_code == 200, (r.status_code, r.text)
        assert r.json()["n"] == 1, r.json()


# --- Frontières d'authentification et de rôle -------------------------------

def test_ordre_des_refus_forum_eteint_avant_jeton_absent():
    """Forum éteint : 503 même sans jeton, jamais 401.

    Un 401 laisserait croire qu'il suffit de se connecter pour voir un forum qui
    n'existe pas sur ce déploiement.
    """
    with contexte(forum_actif=False) as (c, _, _tmp):
        r = c.get("/forum?ex=tp2-ex3")
        assert r.status_code == 503, (r.status_code, r.text)
        assert "discussions" in r.json()["error"], r.json()
    with contexte(moderateurs=["sub-prof"]) as (c, _, _tmp):
        r = c.get("/forum?ex=tp2-ex3")
        assert r.status_code == 401, (r.status_code, r.text)


def test_role_de_moderation_recalcule_et_jamais_recu():
    """Un étudiant qui se déclare modérateur reste un étudiant.

    Le drapeau `moderateur` de la réponse est un drapeau d'AFFICHAGE. Les deux
    routes réservées repartent du `sub` authentifié et de la liste du serveur.
    """
    jetons = {"prof": "sub-prof", "alice": "sub-alice"}
    with contexte(jetons=jetons, moderateurs=["sub-prof"]) as (c, _, _tmp):
        assert c.get("/forum/moderation", headers=auth("prof")).status_code == 200
        r = c.get("/forum/moderation", headers=auth("alice"))
        assert r.status_code == 403, (r.status_code, r.text)
        # Même en le réclamant dans le corps d'une route d'écriture.
        r = c.post("/forum/moderation",
                   json={"id": "0" * 32, "action": "hide",
                         "moderateur": True, "account": "sub-prof"},
                   headers=auth("alice"))
        assert r.status_code == 403, (r.status_code, r.text)


def test_aucune_route_n_accepte_un_identifiant_dans_le_corps():
    """Écrire au nom d'un autre : la seule source de `sub` est le jeton.

    Le contrôle est structurel -- aucun modèle de `schemas.py` ne porte de champ
    d'identité -- et il est aussi éprouvé en vrai ci-dessous.
    """
    import schemas
    interdits = {"account", "sub", "owner", "user", "moderateur",
                 "set_by_moderator"}
    for nom in dir(schemas):
        modele = getattr(schemas, nom)
        champs = getattr(modele, "model_fields", None)
        if champs:
            fuite = interdits & set(champs)
            assert not fuite, (nom, fuite)

    jetons = {"alice": "sub-alice", "bob": "sub-bob"}
    with contexte(jetons=jetons) as (c, base, _tmp):
        r = c.put("/brouillon",
                  json={"exercise_id": "tp2-ex3", "files": {"submission.c": "a moi"},
                        "account": "sub-bob", "sub": "sub-bob"},
                  headers=auth("alice"))
        assert r.status_code == 200, (r.status_code, r.text)
        assert base.brouillons == {("sub-alice", "tp2-ex3"):
                                   {"submission.c": "a moi"}}, base.brouillons


def test_aucun_sub_ne_franchit_la_frontiere_du_forum():
    """Y compris dans la vue la plus renseignée, celle d'un modérateur."""
    jetons = {"prof": "sub-prof", "alice": "sub-alice"}
    with contexte(jetons=jetons, moderateurs=["sub-prof"]) as (c, base, _tmp):
        c.post("/forum", json={"exercise_id": "tp2-ex3", "text": "une question"},
               headers=auth("alice"))
        c.post("/forum/profil",
               json={"display_name": "Alice", "group_number": 4, "display_name_public": True,
                     "group_number_public": True}, headers=auth("alice"))
        r = c.get("/forum?ex=tp2-ex3", headers=auth("prof"))
        assert r.status_code == 200, (r.status_code, r.text)
        assert "sub-alice" not in r.text and "sub-prof" not in r.text, r.text
        assert "Alice" in r.text, r.text


# --- Bornes du contenu du forum ---------------------------------------------

def test_forum_texte_des_deux_cotes_de_la_borne():
    """1 caractère passe, `FORUM_MAX_CHARS` passe, un de plus ne passe pas."""
    from services import forum
    assert forum.forum_texte("")[0] is None
    assert forum.forum_texte("   \n ")[0] is None
    assert forum.forum_texte("a")[0] == "a"
    assert forum.forum_texte("a" * config.FORUM_MAX_CHARS)[0] is not None
    trop, message = forum.forum_texte("a" * (config.FORUM_MAX_CHARS + 1))
    assert trop is None and str(config.FORUM_MAX_CHARS) in message, message


def test_forum_pseudo_bornes_et_noms_reserves():
    """Les étiquettes de l'interface ne se reprennent pas, casse comprise.

    Un message qui se ferait passer pour une réponse du cours ne se rattrape par
    aucune couleur.
    """
    from services import forum
    assert forum.forum_pseudo("a")[0] == "a"
    assert forum.forum_pseudo("a" * config.FORUM_PSEUDO_MAX)[0] is not None
    assert forum.forum_pseudo("a" * (config.FORUM_PSEUDO_MAX + 1))[0] is None
    for reserve in ("Vous", "PARTICIPANT", "Enseignant", "Équipe du cours",
                    "modérateur"):
        nom, message = forum.forum_pseudo(reserve)
        assert nom is None and message, reserve


def test_forum_groupe_liste_fermee_et_champ_libre():
    """Liste non vide : seuls ses numéros. Liste vide : 1..99, bornes comprises."""
    from services import forum
    with contexte(groupes=(4, 6)) as (_c, _b, _tmp):
        assert forum.forum_groupe(4)[0] == 4
        assert forum.forum_groupe("6")[0] == 6
        assert forum.forum_groupe(5)[0] is None
        assert forum.forum_groupe(0)[0] is None
    with contexte(groupes=()) as (_c, _b, _tmp):
        assert forum.forum_groupe(1)[0] == 1
        assert forum.forum_groupe(99)[0] == 99
        assert forum.forum_groupe(0)[0] is None
        assert forum.forum_groupe(100)[0] is None
        assert forum.forum_groupe("douze")[0] is None


def test_identifiant_de_message_et_de_job_hors_forme():
    """32 hexadécimaux minuscules, ni 31, ni 33, ni majuscules."""
    from routers.forum import MSG_RE
    from routers.submission import JOB_RE
    for motif in (MSG_RE, JOB_RE):
        assert motif.match("0" * 32)
        assert not motif.match("0" * 31)
        assert not motif.match("0" * 33)
        assert not motif.match("A" * 32)
        assert not motif.match("0" * 31 + "g")
    with contexte() as (c, _, _tmp):
        assert c.get("/r/pas-un-id").status_code == 400
        assert c.get("/r/" + "0" * 32).status_code == 404


def test_cocher_sans_ecrire_n_affiche_rien():
    """Un champ vide n'est pas un champ visible.

    Sans ça, cocher la case sans rien écrire afficherait « Participant » en
    croyant s'être nommé.
    """
    with contexte(jetons={"alice": "sub-alice"},
                  moderateurs=["sub-prof"]) as (c, base, _tmp):
        r = c.post("/forum/profil",
                   json={"display_name": "", "group_number": None, "display_name_public": True,
                         "group_number_public": True}, headers=auth("alice"))
        assert r.status_code == 200, (r.status_code, r.text)
        profil = base.profils["sub-alice"]
        assert profil["display_name_public"] is False, profil
        assert profil["group_number_public"] is False, profil


# --- Panne de base : 503, jamais un zéro ------------------------------------

def test_base_muette_ne_devient_jamais_un_zero():
    """Annoncer « 0 XP » pendant une panne, c'est dire que le travail a disparu."""
    base = BaseSimulee()
    base.read_progress = lambda user: None
    with contexte(jetons={"alice": "sub-alice"}, base=base) as (c, _, _tmp):
        r = c.get("/progres", headers=auth("alice"))
        assert r.status_code == 503, (r.status_code, r.text)
        assert "xp" not in r.text, r.text


def test_theme_vide_est_un_200_et_une_panne_un_503():
    """Les confondre écraserait le réglage de quelqu'un à la première panne."""
    with contexte(jetons={"alice": "sub-alice"}) as (c, _, _tmp):
        r = c.get("/preferences", headers=auth("alice"))
        assert r.status_code == 200 and r.json() == {"theme": ""}, r.text
    base = BaseSimulee()
    base.read_theme = lambda user: None
    with contexte(jetons={"alice": "sub-alice"}, base=base) as (c, _, _tmp):
        assert c.get("/preferences", headers=auth("alice")).status_code == 503


def test_ecriture_qui_echoue_ne_repond_pas_200():
    """La page n'affiche « enregistré » que sur une réponse vraie."""
    base = BaseSimulee()
    base.write_theme = lambda user, theme: False
    with contexte(jetons={"alice": "sub-alice"}, base=base) as (c, _, _tmp):
        r = c.put("/preferences", json={"theme": "dark"}, headers=auth("alice"))
        assert r.status_code == 503, (r.status_code, r.text)


def test_write_preferences_succeeds_and_says_so():
    """The happy path of PUT /preferences was never verified: neither the
    200, nor the `{"ok": true}` body the page reads to show "saved"."""
    with contexte(jetons={"alice": "sub-alice"}) as (c, base, _tmp):
        r = c.put("/preferences", json={"theme": "dark"}, headers=auth("alice"))
        assert r.status_code == 200 and r.json() == {"ok": True}, r.text
        assert base.themes["sub-alice"] == "dark", base.themes


def test_theme_inconnu_est_refuse():
    """`state.THEMES` est la liste close, et elle est vérifiée avant d'écrire."""
    with contexte(jetons={"alice": "sub-alice"}) as (c, base, _tmp):
        for mauvais in ("", "sepia", "DARK", "light; DROP TABLE"):
            r = c.put("/preferences", json={"theme": mauvais},
                      headers=auth("alice"))
            assert r.status_code == 400, (mauvais, r.status_code)
        assert not base.themes, base.themes


def test_release_dir_and_load_catalog_survive_a_broken_pointer():
    """`release_dir()` never raises: a broken `current.json` returns `None`,
    not a stack trace that would surface to a student.
    """
    from services import catalog as catalogue
    guard = config.PUBLISHED
    tmp = tempfile.mkdtemp(prefix="ctester-published-")
    try:
        config.PUBLISHED = tmp
        assert catalogue.release_dir() is None                 # nothing published
        assert catalogue.load_catalog() is None
        assert catalogue.source_publiee({"id": "x"}, "detail") == (None, None)

        with open(os.path.join(tmp, "current.json"), "w", encoding="utf-8") as fh:
            fh.write("{ this is not JSON")
        assert catalogue.release_dir() is None                 # unreadable

        with open(os.path.join(tmp, "current.json"), "w", encoding="utf-8") as fh:
            json.dump({}, fh)
        assert catalogue.release_dir() is None                 # no "revision"

        with open(os.path.join(tmp, "current.json"), "w", encoding="utf-8") as fh:
            json.dump({"revision": "../../etc"}, fh)
        assert catalogue.release_dir() is None                 # out of form

        with open(os.path.join(tmp, "current.json"), "w", encoding="utf-8") as fh:
            json.dump({"revision": "0123456789abcdef"}, fh)
        assert catalogue.release_dir() is None                 # directory absent

        os.makedirs(os.path.join(tmp, "0123456789abcdef"))
        assert catalogue.release_dir() == os.path.join(tmp, "0123456789abcdef")
        assert catalogue.load_catalog() is None                # catalog.json absent
        with open(os.path.join(tmp, "0123456789abcdef", "catalog.json"),
                  "w", encoding="utf-8") as fh:
            fh.write("[1, 2, 3]")                               # JSON, but not an object
        assert catalogue.load_catalog() is None
    finally:
        config.PUBLISHED = guard
        shutil.rmtree(tmp)


def test_quiz_json_serves_the_published_quiz():
    """The happy path of GET /quiz/<id>.json was never verified."""
    with contexte() as (c, _base, _tmp):
        r = c.get("/quiz/quiz1.json")
        assert r.status_code == 200, r.text
        assert r.json()["questions"][0]["id"] == "q1", r.json()
        assert "answer" not in r.text, r.text


def test_detail_and_quiz_survive_a_rollback_mid_request():
    """Between `find_exercise` and `source_publiee`, the release can
    disappear (a rollback in flight, see services/catalog.py::source_publiee):
    a clean 404, never a stack trace.
    """
    import routers.catalog as catalog_router
    guard = catalog_router.source_publiee
    try:
        with contexte() as (c, _base, _tmp):
            catalog_router.source_publiee = lambda entry, quoi: (None, None)
            r = c.get("/tp/tp2-ex3.json")
            assert r.status_code == 404 and r.json() == {"error": "inconnu"}, r.text
            r = c.get("/quiz/quiz1.json")
            assert r.status_code == 404 and r.json() == {"error": "pas un quiz"}, r.text
    finally:
        catalog_router.source_publiee = guard


def test_etats_and_pratique_during_a_database_outage():
    """Two screens forgotten by the outage check: never a 200 on a mute database."""
    with contexte(jetons={"alice": "sub-alice"}) as (c, base, _tmp):
        assert c.get("/etats", headers=auth("alice")).json() == {"states": []}
        assert c.get("/pratique", headers=auth("alice")).json() == {"practice": []}
        base.etats[("sub-alice", "tp2-ex3")] = "solved"
        r = c.get("/etats", headers=auth("alice"))
        assert r.json() == {"states": [{"exercise_id": "tp2-ex3", "status": "solved"}]}, r.text

    base = BaseSimulee()
    base.read_states = lambda user: None
    base.read_practice_summary = lambda user: None
    with contexte(jetons={"alice": "sub-alice"}, base=base) as (c, _fake, _tmp):
        assert c.get("/etats", headers=auth("alice")).status_code == 503
        assert c.get("/pratique", headers=auth("alice")).status_code == 503


def test_read_draft_refuses_an_unknown_exercise_and_distinguishes_absence():
    """`sources: null` is an exercise never opened, not an outage."""
    with contexte(jetons={"alice": "sub-alice"}) as (c, _base, _tmp):
        r = c.get("/brouillon?ex=inconnu", headers=auth("alice"))
        assert r.status_code == 400 and r.json() == {"error": "TP inconnu"}, r.text

        r = c.get("/brouillon?ex=tp2-ex3", headers=auth("alice"))
        assert r.status_code == 200 and r.json() == {"sources": None}, r.text

        c.put("/brouillon", json={"exercise_id": "tp2-ex3", "files": {"submission.c": "int x;"}},
              headers=auth("alice"))
        r = c.get("/brouillon?ex=tp2-ex3", headers=auth("alice"))
        assert r.json() == {"sources": {"submission.c": "int x;"}}, r.text


def test_write_draft_refuses_a_file_outside_the_allow_list_before_the_quota():
    """The name allow-list is checked BEFORE the write throttle.

    Otherwise a client insisting on a bad file name would exhaust the
    cooldown of someone who saved nothing -- the same defect as for an
    unknown exercise, but on the file-validation side this time (deps.py:65).
    """
    with contexte(jetons={"alice": "sub-alice"}) as (c, base, _tmp):
        for _ in range(5):
            r = c.put("/brouillon",
                      json={"exercise_id": "tp2-ex3", "files": {"hack.c": "x"}},
                      headers=auth("alice"))
            assert r.status_code == 400, r.text
            assert "fichier inattendu" in r.json()["error"], r.text
        assert not base.brouillons
        # The cooldown is intact: a valid write still goes through right
        # away, it was not consumed by the earlier refusals.
        r = c.put("/brouillon",
                  json={"exercise_id": "tp2-ex3", "files": {"submission.c": "x"}},
                  headers=auth("alice"))
        assert r.status_code == 200, r.text


def test_write_draft_during_a_database_outage():
    base = BaseSimulee()
    base.write_draft = lambda *a: False
    with contexte(jetons={"alice": "sub-alice"}, base=base) as (c, _fake, _tmp):
        r = c.put("/brouillon",
                  json={"exercise_id": "tp2-ex3", "files": {"submission.c": "x"}},
                  headers=auth("alice"))
        assert r.status_code == 503, r.text


def test_deleting_the_account_fails_without_leaving_the_illusion_of_success():
    with contexte(jetons={"alice": "sub-alice"}) as (c, base, _tmp):
        base.etats[("sub-alice", "tp2-ex3")] = "solved"
        r = c.delete("/moi", headers=auth("alice"))
        assert r.status_code == 200 and r.json() == {"ok": True}, r.text
        assert c.get("/etats", headers=auth("alice")).json() == {"states": []}

    base = BaseSimulee()
    base.forget = lambda user: False
    with contexte(jetons={"alice": "sub-alice"}, base=base) as (c, _fake, _tmp):
        r = c.delete("/moi", headers=auth("alice"))
        assert r.status_code == 503, r.text


# --- Fichiers servis : ETag, gzip, CSP --------------------------------------

def test_gzip_pile_a_la_borne_de_1024_octets():
    """1023 octets partent tels quels, 1024 partent compressés.

    L'étiquette DIFFÈRE entre les deux représentations (`-gz`) : un cache
    intermédiaire ne doit jamais servir l'une en croyant valider l'autre.
    """
    with contexte() as (c, _, _tmp):
        # Le catalogue est court ; on éprouve la borne sur la fonction elle-même.
        import headers as h

        class FausseRequete:
            def __init__(self, entetes):
                self.headers = entetes

        gzip_ok = FausseRequete({"accept-encoding": "gzip"})
        petit = h.fichier(gzip_ok, b"a" * 1023, "application/json")
        gros = h.fichier(gzip_ok, b"a" * 1024, "application/json")
        assert "content-encoding" not in petit.headers, dict(petit.headers)
        assert gros.headers["content-encoding"] == "gzip", dict(gros.headers)
        assert not petit.headers["etag"].endswith('-gz"')
        assert gros.headers["etag"].endswith('-gz"')
        # Sans `Accept-Encoding: gzip`, la même ressource garde une AUTRE
        # étiquette : deux corps, deux étiquettes.
        nu = h.fichier(FausseRequete({}), b"a" * 1024, "application/json")
        assert nu.headers["etag"] != gros.headers["etag"]


def test_fichier_du_disque_responds_500_when_the_file_is_missing():
    """The catalog promises a file; if it vanished from disk (a rollback in
    flight, corruption), that is a server error, never a bare trace.
    """
    import headers as h

    class FakeRequest:
        headers = {}

    r = h.fichier_du_disque(FakeRequest(), "/path/that/does/not/exist",
                            "missing.json", "application/json")
    assert r.status_code == 500 and json.loads(r.body) == {"error": "fichier manquant"}


def test_the_middleware_ignores_non_http_scopes():
    """The ASGI startup/shutdown ("lifespan") does not go through CORS/Vary:
    the middleware must let it through untouched, not crash on it.
    """
    with TestClient(main.app):
        pass   # entering/exiting the context sends startup then shutdown


def test_entier_falls_back_to_the_default_when_the_variable_is_unreadable():
    os.environ["CTESTER_TEST_ENTIER_INVALIDE"] = "not-a-number"
    try:
        assert config._entier("CTESTER_TEST_ENTIER_INVALIDE", "42") == 42
    finally:
        del os.environ["CTESTER_TEST_ENTIER_INVALIDE"]


def test_304_garde_la_csp_et_le_cache():
    """Une CSP qui n'apparaîtrait que sur le 200 disparaîtrait dès la 2e visite.

    C'est-à-dire presque toujours : le navigateur revalide à chaque chargement.
    """
    page = os.path.join(HERE, "web")
    if not os.path.isdir(page):
        return
    with contexte() as (c, _, _tmp):
        config.PAGE = page
        c2 = TestClient(main.create_app())
        r = c2.get("/")
        assert r.status_code == 200, r.status_code
        assert "content-security-policy" in r.headers, dict(r.headers)
        etiquette = r.headers["etag"]
        r2 = c2.get("/", headers={"If-None-Match": etiquette})
        assert r2.status_code == 304, r2.status_code
        assert r2.headers.get("content-security-policy"), dict(r2.headers)
        assert r2.headers.get("cache-control") == "no-cache", dict(r2.headers)
        assert r2.content == b"", r2.content


def test_page_serves_an_allow_listed_file_other_than_index():
    """`/{nom:path}`: `index.html` has its own test; another name from the
    list (`app.js`) was never served successfully, only its 404 was.
    """
    page = os.path.join(HERE, "web")
    if not os.path.isdir(page):
        return
    with contexte() as (c, _, _tmp):
        config.PAGE = page
        c2 = TestClient(main.create_app())
        r = c2.get("/app.js")
        assert r.status_code == 200, r.status_code
        assert r.headers["content-type"].startswith("text/javascript")


def test_page_sert_une_liste_close_pas_un_repertoire():
    """`StaticFiles` monterait un RÉPERTOIRE. Ici chaque nom est écrit en clair."""
    from routers import page as routeur_page
    with contexte() as (c, _, tmp):
        config.PAGE = os.path.join(tmp, "web")
        with open(os.path.join(config.PAGE, "secret.txt"), "w",
                  encoding="utf-8") as fh:
            fh.write("pas pour toi")
        c2 = TestClient(main.create_app())
        assert c2.get("/secret.txt").status_code == 404
        assert c2.get("/../app/catalog.json").status_code in (404, 400)
        assert "secret.txt" not in routeur_page.SERVIS


def test_page_absente_ne_monte_aucune_route_de_fichier():
    """Sans `CTESTER_PAGE`, cette origine ne répond plus que sur des données.

    C'est l'état visé par la séparation front/back : `/` n'existe plus.
    """
    with contexte() as (c, _, _tmp):
        config.PAGE = ""
        c2 = TestClient(main.create_app())
        assert c2.get("/").status_code == 404
        assert c2.get("/app.js").status_code == 404
        # L'API, elle, répond toujours.
        assert c2.get("/healthz").status_code == 200
        assert c2.get("/catalog.json").status_code == 200


# --- Progression : la première réussite seulement ---------------------------

def test_xp_accorde_une_seule_fois_par_exercice():
    """Rejouer le verdict, ou refaire l'exercice, ne rapporte pas deux fois.

    Les deux tiennent par la même chose : l'identifiant d'événement vaut
    `reussite:<exercice>` et sa clé primaire refuse le doublon. C'est ce qui
    permet de laisser la pratique illimitée sans la rendre farmable.
    """
    with contexte(jetons={"alice": "sub-alice"}) as (c, base, _tmp):
        verdict = {"status": "ok", "passed": 3, "total": 3}
        for numero in range(2):
            job = "%032x" % numero
            os.makedirs(os.path.join(config.SPOOL, job))
            with open(os.path.join(config.SPOOL, job, "job.json"), "w",
                      encoding="utf-8") as fh:
                json.dump({"exercise_id": "tp2-ex3", "owner": "sub-alice"}, fh)
            with open(os.path.join(config.SPOOL, job, "result.json"), "w",
                      encoding="utf-8") as fh:
                json.dump(verdict, fh)
            # Sondé deux fois, comme le fait la page.
            assert c.get("/r/" + job).status_code == 200
            assert c.get("/r/" + job).status_code == 200
        accorde = [t for t in base.xp.values() if t["amount"] > 0]
        assert len(accorde) == 1, base.xp


def test_r_returns_an_anonymous_job_s_verdict_without_recording_it():
    """A job with NO account: the verdict still goes out, and nothing is
    written to the database -- there is nobody to attribute it to.
    """
    with contexte() as (c, base, _tmp):
        job = "a" * 32
        os.makedirs(os.path.join(config.SPOOL, job))
        with open(os.path.join(config.SPOOL, job, "job.json"), "w",
                 encoding="utf-8") as fh:
            json.dump({"exercise_id": "tp2-ex3", "owner": None}, fh)
        with open(os.path.join(config.SPOOL, job, "result.json"), "w",
                 encoding="utf-8") as fh:
            json.dump({"status": "ok", "passed": 1, "total": 1}, fh)
        r = c.get("/r/" + job)
        assert r.status_code == 200 and r.json()["status"] == "ok", r.text
        assert not base.xp and not base.etats, (base.xp, base.etats)


def test_r_records_nothing_if_the_exercise_closed_since_the_submission():
    """Between the submission and the read, the exercise may have closed or
    vanished: the state and the XP are then not written, but the verdict is
    still returned.
    """
    with contexte(jetons={"alice": "sub-alice"}) as (c, base, _tmp):
        job = "b" * 32
        os.makedirs(os.path.join(config.SPOOL, job))
        with open(os.path.join(config.SPOOL, job, "job.json"), "w",
                 encoding="utf-8") as fh:
            json.dump({"exercise_id": "vanished-exercise", "owner": "sub-alice"}, fh)
        with open(os.path.join(config.SPOOL, job, "result.json"), "w",
                 encoding="utf-8") as fh:
            json.dump({"status": "ok", "passed": 1, "total": 1}, fh)
        r = c.get("/r/" + job)
        assert r.status_code == 200 and r.json()["status"] == "ok", r.text
        assert not base.xp and not base.etats, (base.xp, base.etats)


def test_un_echec_n_accorde_rien():
    with contexte(jetons={"alice": "sub-alice"}) as (c, base, _tmp):
        job = "f" * 32
        os.makedirs(os.path.join(config.SPOOL, job))
        with open(os.path.join(config.SPOOL, job, "job.json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"exercise_id": "tp2-ex3", "owner": "sub-alice"}, fh)
        with open(os.path.join(config.SPOOL, job, "result.json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"status": "ok", "passed": 2, "total": 3}, fh)
        assert c.get("/r/" + job).status_code == 200
        assert not base.xp, base.xp
        assert base.etats[("sub-alice", "tp2-ex3")] == "attempted", base.etats


# --- Maîtrise vérifiée : l'autre domaine ------------------------------------

def _verdict(exercise_id, job, resultat):
    """Un job jugé, tel que le worker le laisse dans le spool."""
    os.makedirs(os.path.join(config.SPOOL, job))
    for nom, valeur in (("job.json", {"exercise_id": exercise_id,
                                      "owner": "sub-alice"}),
                        ("result.json", resultat)):
        with open(os.path.join(config.SPOOL, job, nom), "w",
                  encoding="utf-8") as fh:
            json.dump(valeur, fh)


def test_une_verification_laisse_une_evidence_et_aucun_xp():
    """Deux domaines : la vérification mesure, l'XP compte de l'activité.

    CE QUI EST VÉRIFIÉ ICI : qu'une vérification réussie ne verse RIEN au solde
    -- sans quoi elle serait farmable et l'XP se confondrait avec une note --
    et qu'un sondage rejoué n'ajoute pas une évidence de plus.
    """
    with contexte(jetons={"alice": "sub-alice"}) as (c, base, _tmp):
        _verdict("verif-tp2", "a" * 32, {"status": "ok", "passed": 3, "total": 3})
        assert c.get("/r/" + "a" * 32).status_code == 200
        assert c.get("/r/" + "a" * 32).status_code == 200
        assert not base.xp, base.xp
        evidences = [f for f in base.faits if f["type"] == "VerificationEvaluated"]
        assert len(evidences) == 1, base.faits
        assert evidences[0]["payload"]["passed"] is True
        # La charge ne porte QUE de quoi remonter au job : ni code, ni verdict.
        assert set(evidences[0]["payload"]) == {"job", "passed"}

        vue = c.get("/progres", headers=auth("alice")).json()
        assert vue["xp"] == 0, vue
        assert {c_["id"]: c_["band"] for c_ in vue["mastery"]["skills"]} == {
            "variables": "verifie"}
        # Elle ne compte pas non plus comme un exercice de pratique.
        assert vue["exercises"]["total"] == len(CONTENU) - 1, vue["exercises"]
        assert [s["id"] for s in vue["achievements"]] == ["premiere-verification"]


def test_une_verification_ratee_se_lit_a_consolider():
    """Sans la trace d'un échec, « à consolider » n'existerait pas.

    Une compétence tentée sans succès serait alors indistinguable d'une
    compétence jamais abordée, et l'étudiant ne saurait pas où revenir.
    """
    with contexte(jetons={"alice": "sub-alice"}) as (c, base, _tmp):
        _verdict("verif-tp2", "b" * 32, {"status": "ok", "passed": 1, "total": 3})
        assert c.get("/r/" + "b" * 32).status_code == 200
        vue = c.get("/progres", headers=auth("alice")).json()
        assert [c_["band"] for c_ in vue["mastery"]["skills"]] == ["a-consolider"]
        assert not base.xp and not vue["achievements"], (base.xp, vue["achievements"])


def test_les_evidences_muettes_repondent_503():
    """Une bande « pas encore vérifié » ne doit jamais être le zéro d'une panne."""
    base = BaseSimulee()
    base.read_events = lambda *a, **k: None
    with contexte(jetons={"alice": "sub-alice"}, base=base) as (c, _, _tmp):
        r = c.get("/progres", headers=auth("alice"))
        assert r.status_code == 503, (r.status_code, r.text)
        assert "mastery" not in r.text and "xp" not in r.text, r.text


def test_verdict_illisible_ne_boucle_pas():
    """Le worker écrit par rename atomique, donc ce cas est un bug du worker.

    Le dire (500) plutôt que de laisser la page sonder indéfiniment.
    """
    with contexte() as (c, _, _tmp):
        job = "e" * 32
        os.makedirs(os.path.join(config.SPOOL, job))
        with open(os.path.join(config.SPOOL, job, "result.json"), "w",
                  encoding="utf-8") as fh:
            fh.write("{ pas du json")
        r = c.get("/r/" + job)
        assert r.status_code == 500, (r.status_code, r.text)
        assert r.json()["state"] == "error", r.json()


def test_rang_dans_la_file_et_job_disparu():
    """« En cours » n'est pas « 1er dans la file », et un job balayé rend 404."""
    with contexte() as (c, _, _tmp):
        charge = {"key": "cle-de-session", "exercise_id": "tp2-ex3",
                  "files": {"submission.c": "int main(){}"}}
        premier = c.post("/submit", json=charge).json()["id"]
        second = c.post("/submit", json=charge).json()["id"]
        for job, rang in ((premier, 1), (second, 2)):
            corps = c.get("/r/" + job).json()
            assert corps["state"] == "queued" and corps["position"] == rang, corps
        # Le worker prend le premier : il n'est plus « 1er dans la file ».
        open(os.path.join(config.SPOOL, premier, ".lock"), "w").close()
        assert c.get("/r/" + premier).json() == {"state": "running"}
        r = c.get("/r/" + "a" * 32)
        assert r.status_code == 404 and r.json() == {"state": "gone"}, r.text


def test_eta_somme_les_durees_mesurees_et_retombe_sur_une_moyenne():
    """L'ETA est la SOMME des jobs devant, pas un rang fois une constante.

    Un quiz se corrige instantanément, un TP de dix cas paie dix exécutions :
    deux files du même rang n'attendent pas la même chose. Ce que le worker a
    mesuré (`durees.json`) prime ; un exercice jamais vu prend la moyenne des
    autres, et sans aucune mesure la constante pessimiste.
    """
    with contexte() as (c, _, _tmp):
        garde = config.WORKERS
        try:
            config.WORKERS = 1  # sinon l'ETA est divisé, et le calcul illisible
            charge = {"key": "cle-de-session", "exercise_id": "tp2-ex3",
                      "files": {"submission.c": "int main(){}"}}
            premier = c.post("/submit", json=charge).json()["id"]
            second = c.post("/submit", json=charge).json()["id"]

            # 1. Aucune mesure : la constante pessimiste, une fois par job devant.
            assert c.get("/r/" + premier).json()["eta"] == 15
            assert c.get("/r/" + second).json()["eta"] == 30

            # 2. Avec une mesure, c'est ELLE qui compte, pour les deux jobs.
            with open(os.path.join(config.SPOOL, "durees.json"), "w",
                      encoding="utf-8") as fh:
                json.dump({"tp2-ex3": [4.0, 20]}, fh)
            assert c.get("/r/" + premier).json()["eta"] == 4
            assert c.get("/r/" + second).json()["eta"] == 8

            # 3. Un exercice non mesuré prend la moyenne des autres, JAMAIS zéro :
            #    annoncer « tout de suite » sur une file pleine est pire que rien.
            with open(os.path.join(config.SPOOL, "durees.json"), "w",
                      encoding="utf-8") as fh:
                json.dump({"tp1": [2.0, 20], "tp6-ex1": [10.0, 20]}, fh)
            assert c.get("/r/" + premier).json()["eta"] == 6

            # 4. Deux workers dépilent deux fois plus vite.
            config.WORKERS = 2
            assert c.get("/r/" + second).json()["eta"] == 6

            # 5. Un fichier de durées corrompu ne casse pas le sondage.
            with open(os.path.join(config.SPOOL, "durees.json"), "w",
                      encoding="utf-8") as fh:
                fh.write("{ pas du json")
            r = c.get("/r/" + premier)
            assert r.status_code == 200 and r.json()["eta"] > 0, r.text
        finally:
            config.WORKERS = garde


# --- The redesign: private help, helpful marks, leaderboard, collection -----


def test_a_private_question_does_not_cross_the_http_boundary():
    """THE LEAK THAT MUST BE PROVEN FOR REAL, not only in unit tests.

    "Only the lab instructor" is written on the student's form. This check
    goes through the real router, with two real accounts, because that is the
    promise easiest to break by changing one request.
    """
    tokens = {"alice": "sub-alice", "bob": "sub-bob", "prof": "sub-prof"}
    with contexte(jetons=tokens, moderateurs=["sub-prof"]) as (c, fake, _tmp):
        # Alice asks for help: private by default, without even saying so.
        r = c.post("/forum", json={"exercise_id": "tp2-ex3", "text": "stuck",
                                   "step": "compilation",
                                   "blocked_kind": "unclear-error"},
                   headers=auth("alice"))
        assert r.status_code == 200, r.text
        assert fake.messages[0]["visibility"] == "private", fake.messages
        assert fake.messages[0]["step"] == "compilation"

        seen = lambda who: c.get("/forum?ex=tp2-ex3", headers=auth(who)).json()["messages"]
        assert [m["id"] for m in seen("alice")]         # its own author sees it
        assert seen("bob") == []                        # nobody else
        assert len(seen("prof")) == 1                   # the moderator, yes

        # AND ITS AUTHOR CAN OPEN IT TO THEIR GROUP, in one click, with no republishing.
        mid = fake.messages[0]["id"]
        assert c.post("/forum/visibility", json={"id": mid},
                      headers=auth("bob")).status_code == 404   # not theirs
        assert c.post("/forum/visibility", json={"id": mid},
                      headers=auth("alice")).status_code == 200
        assert fake.messages[0]["visibility"] == "group"
        # THE TRANSITION IS ONE-WAY: replayed, it no longer finds a private
        # message -- so nothing to close back, and nothing to hide behind
        # after others have read it.
        assert c.post("/forum/visibility", json={"id": mid},
                      headers=auth("alice")).status_code == 404


def test_helpful_mark_cannot_be_self_voted_and_counts_once():
    """A usefulness counter, not a popularity vote -- and it grants NOTHING.

    Three refusals in a single database statement: the made-up id, one's own
    message, and the duplicate. All three return the same response.
    """
    tokens = {"alice": "sub-alice", "bob": "sub-bob"}
    with contexte(jetons=tokens, moderateurs=["sub-prof"]) as (c, fake, _tmp):
        c.post("/forum", json={"exercise_id": "tp2-ex3", "text": "my answer"},
               headers=auth("alice"))
        mid = fake.messages[0]["id"]
        # One's own message: refused, like a made-up id.
        assert c.post("/forum/helpful", json={"id": mid},
                      headers=auth("alice")).status_code == 404
        assert c.post("/forum/helpful", json={"id": "0" * 32},
                      headers=auth("bob")).status_code == 404
        assert c.post("/forum/helpful", json={"id": mid},
                      headers=auth("bob")).status_code == 200
        # Twice: the primary key refuses, and the route says the same thing.
        assert c.post("/forum/helpful", json={"id": mid},
                      headers=auth("bob")).status_code == 404
        seen = c.get("/forum?ex=tp2-ex3", headers=auth("bob")).json()["messages"][0]
        assert seen["helpful"] == 1 and seen["helped_me"] is True
        # AND NO XP COMES OUT OF IT: marking helpful does not touch progression.
        assert fake.xp == {} and fake.succes == {}


def test_retaining_an_answer_does_not_edit_the_message():
    """Retaining an answer edits nothing: the text is identical before and after.

    That is the message's immutability, which is what keeps a report
    readable. The action lives in the journal, and it is reversible.
    """
    tokens = {"alice": "sub-alice", "prof": "sub-prof"}
    with contexte(jetons=tokens, moderateurs=["sub-prof"]) as (c, fake, _tmp):
        c.post("/forum", json={"exercise_id": "tp2-ex3", "text": "the answer"},
               headers=auth("alice"))
        mid, before = fake.messages[0]["id"], fake.messages[0]["text"]
        # Reserved to the moderator, like hiding.
        assert c.post("/forum/moderation", json={"id": mid, "action": "retain"},
                      headers=auth("alice")).status_code == 403
        assert c.post("/forum/moderation", json={"id": mid, "action": "retain"},
                      headers=auth("prof")).status_code == 200
        assert fake.messages[0]["text"] == before, "the message was edited"
        thread = c.get("/forum?ex=tp2-ex3", headers=auth("alice")).json()
        assert thread["messages"][0]["retained"] is True
        assert thread["state"]["resolved"] == 1
        # REVERSIBLE, and the message still has not moved.
        assert c.post("/forum/moderation", json={"id": mid, "action": "unretain"},
                      headers=auth("prof")).status_code == 200
        assert fake.messages[0]["text"] == before
        assert c.get("/forum?ex=tp2-ex3",
                     headers=auth("alice")).json()["messages"][0]["retained"] is False


def test_who_needs_help_counts_without_naming_and_stays_restricted():
    """The instructor's aggregate: accounts and steps, never people.

    A private question is COUNTED there without being revealed -- that is
    exactly what the student's form promises, and the compromise holds only
    because nothing else comes out.
    """
    tokens = {"alice": "sub-alice", "bob": "sub-bob", "prof": "sub-prof"}
    with contexte(jetons=tokens, moderateurs=["sub-prof"]) as (c, _fake, _tmp):
        for who in ("alice", "bob"):
            c.post("/forum", json={"exercise_id": "tp2-ex3",
                                   "text": "I don't understand the error",
                                   "step": "compilation"}, headers=auth(who))
        assert c.get("/forum/help", headers=auth("alice")).status_code == 403
        r = c.get("/forum/help", headers=auth("prof"))
        assert r.status_code == 200, r.text
        rows = r.json()["rows"]
        assert len(rows) == 1 and rows[0]["people"] == 2, rows
        assert rows[0]["step"] == "compilation"
        # NO `sub`, NO TEXT, NO CODE: a count is enough to know where to go.
        payload = r.text
        for forbidden in ("sub-alice", "sub-bob", "I don't understand"):
            assert forbidden not in payload, payload


def test_the_leaderboard_is_opt_in_and_mute_under_the_cohort():
    """An unticked box is not a hidden row: it is an absence.

    And the alias is DRAWN by the server the moment one ticks the box --
    otherwise ticking the box would lead to a nameless leaderboard, or to a
    400 telling one to press another button first.
    """
    tokens = {"alice": "sub-alice"}
    with contexte(jetons=tokens, moderateurs=["sub-prof"]) as (c, fake, _tmp):
        r = c.get("/leaderboard", headers=auth("alice"))
        assert r.status_code == 200 and r.json()["participating"] is False

        r = c.post("/forum/profil",
                   json={"group_number": 4, "leaderboard_opt_in": True},
                   headers=auth("alice"))
        assert r.status_code == 200, r.text
        alias = fake.profils["sub-alice"]["alias"]
        assert alias and alias in politique.possible_aliases(), alias

        view = c.get("/leaderboard", headers=auth("alice")).json()
        assert view["participating"] is True and view["me"]["rank"] == 1
        # UNDER THE MINIMUM COHORT: one's own row, no table.
        assert view["rows"] == [] and view["cohort"] < view["minimum"]
        # AND NO `sub` COMES OUT, no more than elsewhere.
        assert "sub-alice" not in c.get("/leaderboard", headers=auth("alice")).text

        # THE ALIAS REDRAWS, as often as one likes.
        # A BODY, EVEN EMPTY: the middleware bounds every POST before
        # parsing, and a missing `Content-Length` counts as out of bounds.
        r = c.post("/leaderboard/alias", json={}, headers=auth("alice"))
        assert r.status_code == 200 and r.json()["alias"] != alias

        # OPTING OUT ERASES NOTHING ELSE: the group and the name stay.
        c.post("/forum/profil", json={"group_number": 4,
                                      "leaderboard_opt_in": False},
               headers=auth("alice"))
        assert fake.profils["sub-alice"]["group_number"] == 4
        assert c.get("/leaderboard", headers=auth("alice")
                     ).json()["participating"] is False


def test_a_locked_frame_is_refused():
    """The frame is decorative, but "which ones do I have" is still a fact.

    The list comes from the server, computed on the level actually reached:
    the browser never gets to assert it.
    """
    with contexte(jetons={"alice": "sub-alice"},
                  moderateurs=["sub-prof"]) as (c, _fake, _tmp):
        offered = c.get("/forum/profil", headers=auth("alice")).json()["frames"]
        assert [f["id"] for f in offered] == ["simple"], offered
        r = c.post("/forum/profil", json={"plate_frame": "tolerance"},
                   headers=auth("alice"))
        assert r.status_code == 400, r.text
        assert c.post("/forum/profil", json={"plate_frame": "simple"},
                      headers=auth("alice")).status_code == 200


def test_the_collection_shows_locked_cards_with_their_condition():
    """A grey card says under what condition it drops. Nothing is drawn.

    That is the difference between a collection and a loot box, and it reads
    in the payload: every card carries its condition, held or not.
    """
    with contexte(jetons={"alice": "sub-alice"},
                  moderateurs=["sub-prof"]) as (c, _fake, _tmp):
        r = c.get("/collection", headers=auth("alice"))
        assert r.status_code == 200, r.text
        cards = r.json()["cards"]
        assert len(cards) == len(politique.POLICY["cards"])
        assert all(not card["held"] for card in cards)
        assert all(card["condition"] for card in cards), cards
        # Under the minimum cohort, no rarity is announced.
        assert all(card["rarity"] is None for card in cards)


def test_a_mute_database_answers_503_on_the_new_screens():
    """No invented number during an outage, on either new screen.

    "0 XP", "nobody on the leaderboard", "no card": all three tell someone
    their work is gone, and all three would be false.
    """
    class Mute(BaseSimulee):
        leaderboard_rows = staticmethod(lambda *a: None)
        read_unlock_rates = staticmethod(lambda *a: None)
        read_practice_days = staticmethod(lambda *a: None)

    with contexte(jetons={"alice": "sub-alice"}, base=Mute(),
                  moderateurs=["sub-prof"]) as (c, _fake, _tmp):
        for route in ("/leaderboard", "/collection", "/progres"):
            r = c.get(route, headers=auth("alice"))
            assert r.status_code == 503, (route, r.status_code, r.text)
            assert not re.search(r"\\d", r.json().get("error", "")), r.text


def test_forum_id_based_routes_reject_an_invalid_form():
    """`_message_id()` is the common gate for five routes; out of form,
    all of them respond 400 before touching the database.
    """
    tokens = {"alice": "sub-alice", "prof": "sub-prof"}
    with contexte(jetons=tokens, moderateurs=["sub-prof"]) as (c, _fake, _tmp):
        calls = [
            lambda: c.post("/forum/visibility", json={"id": "too-short"},
                          headers=auth("alice")),
            lambda: c.post("/forum/helpful", json={"id": "too-short"},
                          headers=auth("alice")),
            lambda: c.delete("/forum?id=too-short", headers=auth("alice")),
            lambda: c.post("/forum/signalement",
                          json={"id": "too-short", "kind": "message"},
                          headers=auth("alice")),
            lambda: c.post("/forum/moderation",
                          json={"id": "too-short", "action": "hide"},
                          headers=auth("prof")),
        ]
        for call in calls:
            r = call()
            assert r.status_code == 400 and r.json() == {"error": "identifiant invalide"}, r.text


def test_delete_ones_own_message_never_someone_elses():
    """DELETE /forum was never tested anywhere: neither success nor refusal."""
    tokens = {"alice": "sub-alice", "bob": "sub-bob"}
    with contexte(jetons=tokens, moderateurs=["sub-prof"]) as (c, fake, _tmp):
        c.post("/forum", json={"exercise_id": "tp2-ex3", "text": "mine"},
               headers=auth("alice"))
        mid = fake.messages[0]["id"]
        # A well-formed id that does not exist: the same 404 as someone
        # else's message, so nothing more is revealed.
        r = c.delete("/forum?id=" + "0" * 32, headers=auth("alice"))
        assert r.status_code == 404, r.text
        r = c.delete("/forum?id=" + mid, headers=auth("bob"))
        assert r.status_code == 404, (r.status_code, r.text)
        assert fake.messages, "bob's message should not have disappeared"
        r = c.delete("/forum?id=" + mid, headers=auth("alice"))
        assert r.status_code == 200 and r.json() == {"ok": True}, r.text
        assert not fake.messages

    base = BaseSimulee()
    base.forum_supprimer = lambda *a: None
    with contexte(jetons={"alice": "sub-alice"}, base=base,
                 moderateurs=["sub-prof"]) as (c, _fake, _tmp):
        r = c.delete("/forum?id=" + "0" * 32, headers=auth("alice"))
        assert r.status_code == 503, r.text


def test_report_a_message_or_a_name():
    """POST /forum/signalement had no test at all: neither the message nor the name."""
    tokens = {"alice": "sub-alice", "bob": "sub-bob"}
    with contexte(jetons=tokens, moderateurs=["sub-prof"]) as (c, fake, _tmp):
        c.post("/forum", json={"exercise_id": "tp2-ex3", "text": "dubious"},
               headers=auth("alice"))
        mid = fake.messages[0]["id"]
        r = c.post("/forum/signalement", json={"id": mid, "kind": "message"},
                   headers=auth("bob"))
        assert r.status_code == 200 and r.json() == {"ok": True}, r.text
        r = c.post("/forum/signalement", json={"id": mid, "kind": "name"},
                   headers=auth("bob"))
        assert r.status_code == 200 and r.json() == {"ok": True}, r.text
        # `kind` absent: the schema's default is a message report.
        r = c.post("/forum/signalement", json={"id": mid}, headers=auth("bob"))
        assert r.status_code == 200, r.text

    base = BaseSimulee()
    base.forum_signaler = lambda *a: None
    base.forum_nom_signaler = lambda *a: None
    with contexte(jetons={"alice": "sub-alice"}, base=base,
                 moderateurs=["sub-prof"]) as (c, _fake, _tmp):
        for body in ({"id": "0" * 32, "kind": "message"},
                     {"id": "0" * 32, "kind": "name"}):
            r = c.post("/forum/signalement", json=body, headers=auth("alice"))
            assert r.status_code == 503, (body, r.text)


def test_moderation_clears_a_reported_name_without_touching_the_rest_of_the_profile():
    """`clear-name` was never tested anywhere -- neither the success nor its
    three failure modes.
    """
    tokens = {"alice": "sub-alice", "prof": "sub-prof"}
    with contexte(jetons=tokens, moderateurs=["sub-prof"]) as (c, fake, _tmp):
        c.post("/forum/profil",
              json={"display_name": "Léa", "display_name_public": True,
                    "group_number": 4, "group_number_public": True},
              headers=auth("alice"))
        c.post("/forum", json={"exercise_id": "tp2-ex3", "text": "hi"},
               headers=auth("alice"))
        mid = fake.messages[0]["id"]
        r = c.post("/forum/moderation", json={"id": mid, "action": "clear-name"},
                   headers=auth("prof"))
        assert r.status_code == 200 and r.json() == {"ok": True}, r.text
        profile = fake.profils["sub-alice"]
        assert profile["display_name"] is None
        # The rest of the profile survives the write: ONLY the name leaves.
        assert profile["group_number"] == 4 and profile["group_number_public"] is True

        # A well-formed id whose message has no retrievable author.
        r = c.post("/forum/moderation", json={"id": "0" * 32, "action": "clear-name"},
                   headers=auth("prof"))
        assert r.status_code == 404, r.text

    base = BaseSimulee()
    base.forum_profil = lambda user: None
    with contexte(jetons={"alice": "sub-alice", "prof": "sub-prof"}, base=base,
                 moderateurs=["sub-prof"]) as (c, fake, _tmp):
        fake.messages.append({"id": "1" * 32, "exercise_id": "tp2-ex3",
                              "account": "sub-alice", "text": "x", "hidden": False,
                              "step": None, "blocked_kind": None,
                              "visibility": "thread", "created_at": "2026-09-04"})
        r = c.post("/forum/moderation", json={"id": "1" * 32, "action": "clear-name"},
                   headers=auth("prof"))
        assert r.status_code == 503, r.text

    base2 = BaseSimulee()
    base2.forum_profil_ecrire = lambda *a, **k: False
    with contexte(jetons={"alice": "sub-alice", "prof": "sub-prof"}, base=base2,
                 moderateurs=["sub-prof"]) as (c, fake, _tmp):
        fake.messages.append({"id": "2" * 32, "exercise_id": "tp2-ex3",
                              "account": "sub-alice", "text": "x", "hidden": False,
                              "step": None, "blocked_kind": None,
                              "visibility": "thread", "created_at": "2026-09-04"})
        r = c.post("/forum/moderation", json={"id": "2" * 32, "action": "clear-name"},
                   headers=auth("prof"))
        assert r.status_code == 503, r.text


def test_moderation_refuses_an_unknown_action():
    tokens = {"prof": "sub-prof"}
    with contexte(jetons=tokens, moderateurs=["sub-prof"]) as (c, _fake, _tmp):
        r = c.post("/forum/moderation", json={"id": "0" * 32, "action": "edit"},
                   headers=auth("prof"))
        assert r.status_code == 400 and r.json() == {"error": "action inconnue"}, r.text


def test_fil_refuses_an_unknown_exercise():
    with contexte(jetons={"alice": "sub-alice"},
                 moderateurs=["sub-prof"]) as (c, _fake, _tmp):
        r = c.get("/forum?ex=inconnu", headers=auth("alice"))
        assert r.status_code == 400 and r.json() == {"error": "TP inconnu"}, r.text


def test_visibility_and_helpful_report_a_database_outage():
    base = BaseSimulee()
    base.forum_open_to_group = lambda *a: None
    with contexte(jetons={"alice": "sub-alice"}, base=base,
                 moderateurs=["sub-prof"]) as (c, _fake, _tmp):
        r = c.post("/forum/visibility", json={"id": "0" * 32}, headers=auth("alice"))
        assert r.status_code == 503, r.text

    base = BaseSimulee()
    base.forum_mark_helpful = lambda *a: None
    with contexte(jetons={"alice": "sub-alice"}, base=base,
                 moderateurs=["sub-prof"]) as (c, _fake, _tmp):
        r = c.post("/forum/helpful", json={"id": "0" * 32}, headers=auth("alice"))
        assert r.status_code == 503, r.text


def test_moderer_hide_restore_retain_report_an_outage_and_an_unknown_id():
    """`hide`/`restore`/`retain`/`unretain` share the same 503 and 404 as
    `clear-name`, but through a different code path (`state.forum_moderer`).
    """
    tokens = {"alice": "sub-alice", "prof": "sub-prof"}
    with contexte(jetons=tokens, moderateurs=["sub-prof"]) as (c, fake, _tmp):
        c.post("/forum", json={"exercise_id": "tp2-ex3", "text": "x"},
              headers=auth("alice"))
        mid = fake.messages[0]["id"]
        r = c.post("/forum/moderation", json={"id": mid, "action": "hide"},
                   headers=auth("prof"))
        assert r.status_code == 200 and r.json() == {"ok": True}, r.text
        assert fake.messages[0]["hidden"] is True
        r = c.post("/forum/moderation", json={"id": "0" * 32, "action": "restore"},
                   headers=auth("prof"))
        assert r.status_code == 404, r.text

    base = BaseSimulee()
    base.forum_moderer = lambda *a: None
    with contexte(jetons=tokens, base=base, moderateurs=["sub-prof"]) as (c, _fake, _tmp):
        r = c.post("/forum/moderation", json={"id": "0" * 32, "action": "hide"},
                   headers=auth("prof"))
        assert r.status_code == 503, r.text


def test_forum_reports_a_database_outage_on_each_read_route():
    """GET /forum, /forum/moderation and /forum/help: each its own outage."""
    base = BaseSimulee()
    base.forum_fil = lambda *a, **k: None
    with contexte(jetons={"alice": "sub-alice"}, base=base,
                 moderateurs=["sub-prof"]) as (c, _fake, _tmp):
        r = c.get("/forum?ex=tp2-ex3", headers=auth("alice"))
        assert r.status_code == 503, r.text

    base = BaseSimulee()
    base.forum_signalements = lambda *a: None
    with contexte(jetons={"prof": "sub-prof"}, base=base,
                 moderateurs=["sub-prof"]) as (c, _fake, _tmp):
        r = c.get("/forum/moderation", headers=auth("prof"))
        assert r.status_code == 503, r.text

    base = BaseSimulee()
    base.forum_help_rows = lambda *a: None
    with contexte(jetons={"prof": "sub-prof"}, base=base,
                 moderateurs=["sub-prof"]) as (c, _fake, _tmp):
        r = c.get("/forum/help", headers=auth("prof"))
        assert r.status_code == 503, r.text


def test_publier_validates_each_field_then_reports_an_outage():
    """POST /forum: the exercise, the text, the step, the block, the
    visibility -- each refusal must arrive BEFORE freiner_forum, and a write
    that fails must respond 503, never 200.
    """
    with contexte(jetons={"alice": "sub-alice"},
                 moderateurs=["sub-prof"]) as (c, _fake, _tmp):
        r = c.post("/forum", json={"exercise_id": "inconnu", "text": "x"},
                   headers=auth("alice"))
        assert r.status_code == 400 and r.json() == {"error": "TP inconnu"}, r.text

        r = c.post("/forum", json={"exercise_id": "tp2-ex3", "text": ""},
                   headers=auth("alice"))
        assert r.status_code == 400, r.text

        r = c.post("/forum", json={"exercise_id": "tp2-ex3", "text": "x",
                                   "step": "whatever"},
                   headers=auth("alice"))
        assert r.status_code == 400, r.text

        r = c.post("/forum", json={"exercise_id": "tp2-ex3", "text": "x",
                                   "step": "compilation",
                                   "blocked_kind": "whatever"},
                   headers=auth("alice"))
        assert r.status_code == 400, r.text

        # A "group" visibility refused outright: it is never a choice at
        # publish time, only `open_to_group` performs that transition.
        r = c.post("/forum", json={"exercise_id": "tp2-ex3", "text": "x",
                                   "visibility": "group"},
                   headers=auth("alice"))
        assert r.status_code == 400, r.text

    base = BaseSimulee()
    base.forum_publier = lambda *a: False
    with contexte(jetons={"alice": "sub-alice"}, base=base,
                 moderateurs=["sub-prof"]) as (c, _fake, _tmp):
        r = c.post("/forum", json={"exercise_id": "tp2-ex3", "text": "x"},
                   headers=auth("alice"))
        assert r.status_code == 503, r.text


def test_profil_validates_the_name_and_group_then_reports_an_outage():
    with contexte(jetons={"alice": "sub-alice"}, groupes=(4, 6),
                 moderateurs=["sub-prof"]) as (c, _fake, _tmp):
        r = c.post("/forum/profil", json={"display_name": "x" * 999},
                   headers=auth("alice"))
        assert r.status_code == 400, r.text
        r = c.post("/forum/profil", json={"group_number": 999},
                   headers=auth("alice"))
        assert r.status_code == 400, r.text

    base = BaseSimulee()
    base.forum_profil = lambda user: None
    with contexte(jetons={"alice": "sub-alice"}, base=base,
                 moderateurs=["sub-prof"]) as (c, _fake, _tmp):
        r = c.get("/forum/profil", headers=auth("alice"))
        assert r.status_code == 503, r.text
        r = c.post("/forum/profil", json={"display_name": "Léa"},
                   headers=auth("alice"))
        assert r.status_code == 503, r.text

    base = BaseSimulee()
    base.forum_profil_ecrire = lambda *a, **k: False
    with contexte(jetons={"alice": "sub-alice"}, base=base,
                 moderateurs=["sub-prof"]) as (c, _fake, _tmp):
        r = c.post("/forum/profil", json={"display_name": "Léa"},
                   headers=auth("alice"))
        assert r.status_code == 503, r.text

    base = BaseSimulee()
    base.forum_taken_aliases = lambda: None
    with contexte(jetons={"alice": "sub-alice"}, base=base,
                 moderateurs=["sub-prof"]) as (c, _fake, _tmp):
        r = c.post("/forum/profil", json={"leaderboard_opt_in": True},
                   headers=auth("alice"))
        assert r.status_code == 503, r.text


def test_oidc_json_is_empty_when_sign_in_is_disabled():
    """"Nothing more to offer": the sign-in block stays inert."""
    assert client.get("/oidc.json").json() == {}


def test_sub_responds_503_outside_oidc_configuration():
    """503, not 401: "there are no accounts here" is not "sign in again"."""
    r = client.get("/etats", headers=auth("alice"))
    assert r.status_code == 503 and "persistance" in r.json()["error"], r.text


def test_freiner_forum_blocks_a_burst_of_messages():
    # `contexte()` restores `deps.forum_quota` on exit -- no need to do it here.
    with contexte(jetons={"alice": "sub-alice"},
                 moderateurs=["sub-prof"]) as (c, _fake, _tmp):
        deps.forum_quota = quotas.Quota(cooldown=999, hourly=100)
        r1 = c.post("/forum", json={"exercise_id": "tp2-ex3", "text": "one"},
                   headers=auth("alice"))
        assert r1.status_code == 200, r1.text
        r2 = c.post("/forum", json={"exercise_id": "tp2-ex3", "text": "two"},
                   headers=auth("alice"))
        assert r2.status_code == 429 and "retry_after" in r2.json(), r2.text


def test_leaderboard_and_alias_report_every_database_outage():
    base = BaseSimulee()
    base.forum_profil = lambda user: None
    with contexte(jetons={"alice": "sub-alice"}, base=base,
                 moderateurs=["sub-prof"]) as (c, _fake, _tmp):
        assert c.get("/leaderboard", headers=auth("alice")).status_code == 503
        assert c.post("/leaderboard/alias", json={}, headers=auth("alice")).status_code == 503

    base = BaseSimulee()
    base.forum_taken_aliases = lambda: None
    with contexte(jetons={"alice": "sub-alice"}, base=base,
                 moderateurs=["sub-prof"]) as (c, _fake, _tmp):
        r = c.post("/leaderboard/alias", json={}, headers=auth("alice"))
        assert r.status_code == 503, r.text

    base = BaseSimulee()
    base.forum_profil_ecrire = lambda *a, **k: False
    with contexte(jetons={"alice": "sub-alice"}, base=base,
                 moderateurs=["sub-prof"]) as (c, fake, _tmp):
        fake.profils["sub-alice"] = dict(BaseSimulee.EMPTY_PROFILE, alias="Faucon-12")
        r = c.post("/leaderboard/alias", json={}, headers=auth("alice"))
        assert r.status_code == 503, r.text


def test_redraw_alias_exhausts_the_vocabulary():
    """The closed vocabulary is finite: no more pseudonym -> 503, never a
    server-invented name as a stopgap.
    """
    import policy
    every_alias = set(policy.possible_aliases())
    base = BaseSimulee()
    with contexte(jetons={"alice": "sub-alice"}, base=base,
                 moderateurs=["sub-prof"]) as (c, fake, _tmp):
        # The whole vocabulary is already taken by OTHER accounts: none is
        # left to draw for alice, whatever her own alias is.
        for i, alias in enumerate(every_alias):
            fake.profils["sub-%d" % i] = dict(BaseSimulee.EMPTY_PROFILE, alias=alias)
        r = c.post("/leaderboard/alias", json={}, headers=auth("alice"))
        assert r.status_code == 503 and "pseudonyme" in r.json()["error"], r.text


def test_avertir_reports_each_incomplete_configuration_independently():
    """`_avertir()` never blocks startup: three silent warnings, each
    independent of the other two (see the docstring of app/main.py::_avertir).
    """
    guard = (config.OIDC_ISSUER, config.FORUM_MODERATORS, config.DOCS,
             security.oidc_enabled)
    try:
        # 1. An issuer configured but OIDC not really active (e.g. no
        # database): only the sign-in warning.
        config.OIDC_ISSUER = "https://auth.exemple"
        config.FORUM_MODERATORS = frozenset({"sub-prof"})
        config.DOCS = False
        security.oidc_enabled = lambda: False
        buffer = io.StringIO()
        with contextlib.redirect_stderr(buffer):
            main._avertir()
        out = buffer.getvalue()
        assert "connexion desactivee" in out
        assert "discussions desactivees" not in out
        assert "CTESTER_DOCS" not in out

        # 2. OIDC really active but no moderator: the forum, silent.
        security.oidc_enabled = lambda: True
        config.FORUM_MODERATORS = frozenset()
        buffer = io.StringIO()
        with contextlib.redirect_stderr(buffer):
            main._avertir()
        out = buffer.getvalue()
        assert "connexion desactivee" not in out
        assert "discussions desactivees" in out

        # 3. Public documentation depends on nothing else.
        config.OIDC_ISSUER = ""
        config.FORUM_MODERATORS = frozenset({"sub-prof"})
        config.DOCS = True
        buffer = io.StringIO()
        with contextlib.redirect_stderr(buffer):
            main._avertir()
        out = buffer.getvalue()
        assert "CTESTER_DOCS=1" in out
        assert "connexion desactivee" not in out
        assert "discussions desactivees" not in out

        # 4. Everything is in order: complete silence.
        config.OIDC_ISSUER = "https://auth.exemple"
        config.DOCS = False
        security.oidc_enabled = lambda: True
        buffer = io.StringIO()
        with contextlib.redirect_stderr(buffer):
            main._avertir()
        assert buffer.getvalue() == ""
    finally:
        (config.OIDC_ISSUER, config.FORUM_MODERATORS, config.DOCS,
         security.oidc_enabled) = guard


def test_http_exception_handler_only_rewrites_the_generic_404():
    """`_http()` only replaces "Not Found" on Starlette's generic 404
    (unknown route): a future application-level 404, with its own message,
    must stay readable and not be overwritten.
    """
    import asyncio
    from starlette.exceptions import HTTPException as StarletteHTTPException
    handler = main.app.exception_handlers[StarletteHTTPException]
    response = asyncio.run(handler(
        None, StarletteHTTPException(status_code=404, detail="Not Found")))
    assert json.loads(response.body) == {"error": "inconnu"}
    response = asyncio.run(handler(
        None, StarletteHTTPException(status_code=404, detail="exercice retiré")))
    assert json.loads(response.body) == {"error": "exercice retiré"}


def test_uvicorn_is_launched_with_a_single_worker():
    """A non-negotiable invariant (see app/main.py's docstring): a second
    worker would silently double quotas, presence and the OIDC token cache,
    all in process memory. A source check rather than an execution one --
    launching a real server is not the point here, and the whole point is
    that nobody copies this line with `--workers 4`.
    """
    source = pathlib.Path(main.__file__).read_text(encoding="utf-8")
    block = source.split("uvicorn.run(", 1)[1].split(")", 1)[0]
    assert re.search(r"workers\s*=\s*1\b", block), block
    assert not re.search(r"workers\s*=\s*(?!1\b)\d", block), block


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        fn()
        print("ok   " + fn.__name__)
    print("\n%d vérifications passées." % len(tests))
