#!/usr/bin/env python3
"""La frontière HTTP de l'API FastAPI, éprouvée par `fastapi.testclient`.

Ce fichier reprend le rôle que `test_http_end_to_end` tenait pour la v1 : ce qui
se voit depuis un navigateur -- codes, en-têtes, formes de corps -- et surtout
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
import json
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
import etat        # noqa: E402
import main        # noqa: E402
import security    # noqa: E402
from services import quotas  # noqa: E402

CONNUE = "https://tch009.thevhome.com"
INCONNUE = "https://mechant.example"

client = TestClient(main.app)


# --- Harnais ----------------------------------------------------------------

def _modules_avec_etat():
    """Tous les modules qui ont importé `etat`, pour le remplacer PARTOUT.

    L'ancien harnais posait `app.etat = faux` et c'était fini : il n'y avait
    qu'un fichier. Maintenant `security`, `services.forum`, `services.progression`
    et quatre routeurs l'importent chacun de leur côté. En oublier un ferait
    parler un test à une VRAIE base -- absente en test, donc `enabled()` faux,
    donc des 503 partout et un contrôle qui « passe » sans rien avoir éprouvé.

    Le balayage est dynamique exprès : un module ajouté demain est couvert sans
    que personne n'ait à penser à cette liste.
    """
    return [m for m in list(sys.modules.values())
            if getattr(m, "etat", None) is etat]


class BaseSimulee:
    """Une base en mémoire. Chaque méthode rend ce que `etat.py` promet.

    `None` VEUT DIRE « LA BASE N'A PAS RÉPONDU », et c'est la moitié la plus
    importante du contrat : les routes doivent alors répondre 503, jamais 200
    avec un zéro. Les tests de panne remplacent une méthode par `lambda *_: None`.
    """

    STATUSES = ("essaye", "valide")
    THEMES = ("light", "dark")
    enabled = staticmethod(lambda: True)

    def __init__(self):
        self.brouillons, self.etats, self.themes = {}, {}, {}
        self.messages, self.profils = [], {}
        self.pratique, self.jobs = {}, set()
        self.evenements, self.xp, self.succes = {}, {}, {}

    # -- comptes
    def read_resume(self, user, ex):
        return self.brouillons.get((user, ex))

    def write_draft(self, user, ex, sources):
        self.brouillons[(user, ex)] = sources
        return True

    def read_states(self, user):
        return [{"exercice_id": ex, "statut": s}
                for (u, ex), s in self.etats.items() if u == user]

    def write_state(self, user, ex, statut, sources):
        self.etats[(user, ex)] = statut
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
        self.messages = [m for m in self.messages if m["utilisateur"] != user]
        return True

    # -- pratique et progression
    def read_practice_summary(self, user):
        return [{"exercice_id": ex, "tentatives": n, "reussites": r}
                for (u, ex), (n, r) in self.pratique.items() if u == user]

    def write_practice_attempt(self, user, job_id, ex, result):
        if job_id not in self.jobs:
            self.jobs.add(job_id)
            n, r = self.pratique.get((user, ex), (0, 0))
            gagne = (result.get("total", 0) > 0
                     and result.get("passed") == result.get("total"))
            self.pratique[(user, ex)] = (n + 1, r + int(gagne))
        return True

    def grant_first_solve(self, user, ex, event_id, amount, motif, policy,
                          payload, daily_cap):
        # LA CLÉ EST LE FAIT, pas l'appel : rejouer le même verdict retombe sur
        # la même clé et ne crée rien.
        if (user, event_id) in self.evenements:
            return None
        self.evenements[(user, event_id)] = payload
        deja = sum(t["montant"] for (u, _), t in self.xp.items() if u == user)
        self.xp[(user, event_id)] = {
            "exercice_id": ex, "montant": max(min(amount, daily_cap - deja), 0),
            "motif": motif, "accorde_le": "2026-09-04"}
        return self.xp[(user, event_id)]["montant"]

    def unlock(self, user, ids, event_id, policy):
        for succes_id in ids:
            self.succes.setdefault((user, succes_id),
                                   {"id": succes_id, "obtenu_le": "2026-09-04",
                                    "politique": policy})
        return True

    def read_progress(self, user):
        mien = lambda t: [v for (u, _), v in sorted(t.items()) if u == user]  # noqa: E731
        return {"xp": sum(t["montant"] for t in mien(self.xp)),
                "succes": mien(self.succes), "transactions": mien(self.xp)}

    # -- forum
    def forum_fil(self, ex, limite):
        return [dict(m) for m in self.messages
                if m["exercice_id"] == ex][:limite]

    def forum_publier(self, mid, ex, user, texte):
        self.messages.append({"id": mid, "exercice_id": ex, "utilisateur": user,
                              "texte": texte, "masque": False,
                              "cree_le": "2026-09-04"})
        return True

    def forum_supprimer(self, mid, user):
        avant = len(self.messages)
        self.messages = [m for m in self.messages
                         if not (m["id"] == mid and m["utilisateur"] == user)]
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
                m["masque"] = (action == "masquer")
                return True
        return False

    def forum_auteur(self, mid):
        for m in self.messages:
            if m["id"] == mid:
                return m["utilisateur"]
        return None

    def forum_profil(self, user):
        return self.profils.get(user, {"pseudo": None, "groupe": None,
                                       "pseudo_public": False,
                                       "groupe_public": False})

    def forum_profils(self, users):
        return {u: self.profils[u] for u in users if u in self.profils}

    def forum_profil_ecrire(self, pid, user, pseudo, groupe, pseudo_public,
                            groupe_public, par_moderateur=False):
        self.profils[user] = {"pseudo": pseudo, "groupe": groupe,
                              "pseudo_public": pseudo_public,
                              "groupe_public": groupe_public}
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
    import content_catalogue
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
    garde_etat = [(m, m.etat) for m in modules]
    garde_config = {n: getattr(config, n) for n in
                    ("PUBLISHED", "SPOOL", "PAGE", "KEY", "OIDC_ISSUER",
                     "OIDC_CLIENT_ID", "FORUM_MODERATORS", "FORUM_GROUPES")}
    garde_secu = (security.current_user, security.current_name)
    garde_quotas = (deps.quota, deps.state_quota, deps.forum_quota, deps.presence)

    for m in modules:
        m.etat = faux
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
    deps.state_quota = quotas.Quota(cooldown=0, hourly=100000)
    deps.forum_quota = quotas.Quota(cooldown=0, hourly=100000)
    deps.presence = quotas.Presence()

    try:
        yield TestClient(main.create_app()), faux, tmp
    finally:
        for m, ancien in garde_etat:
            m.etat = ancien
        for nom, valeur in garde_config.items():
            setattr(config, nom, valeur)
        security.current_user, security.current_name = garde_secu
        (deps.quota, deps.state_quota, deps.forum_quota,
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
    import content_catalogue
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
        from services import catalogue
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


def test_identifiant_d_exercice_hors_forme():
    """Un chemin n'est pas un identifiant, et il ne le devient jamais.

    `find_exercise` COMPARE À L'IDENTIFIANT DU CATALOGUE, il ne le concatène
    pas : c'est ce qui fait que `/tp/../catalog.json` n'est pas un chemin à
    traverser mais un nom qui n'existe pas. Le chemin lu, lui, est reconstruit
    par `source_publiee` depuis l'entrée trouvée -- jamais depuis l'URL.
    """
    from services import catalogue
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
                   json={"id": "0" * 32, "action": "masquer",
                         "moderateur": True, "utilisateur": "sub-prof"},
                   headers=auth("alice"))
        assert r.status_code == 403, (r.status_code, r.text)


def test_aucune_route_n_accepte_un_identifiant_dans_le_corps():
    """Écrire au nom d'un autre : la seule source de `sub` est le jeton.

    Le contrôle est structurel -- aucun modèle de `schemas.py` ne porte de champ
    d'identité -- et il est aussi éprouvé en vrai ci-dessous.
    """
    import schemas
    interdits = {"utilisateur", "sub", "owner", "user", "moderateur",
                 "par_moderateur"}
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
                        "utilisateur": "sub-bob", "sub": "sub-bob"},
                  headers=auth("alice"))
        assert r.status_code == 200, (r.status_code, r.text)
        assert base.brouillons == {("sub-alice", "tp2-ex3"):
                                   {"submission.c": "a moi"}}, base.brouillons


def test_aucun_sub_ne_franchit_la_frontiere_du_forum():
    """Y compris dans la vue la plus renseignée, celle d'un modérateur."""
    jetons = {"prof": "sub-prof", "alice": "sub-alice"}
    with contexte(jetons=jetons, moderateurs=["sub-prof"]) as (c, base, _tmp):
        c.post("/forum", json={"exercise_id": "tp2-ex3", "texte": "une question"},
               headers=auth("alice"))
        c.post("/forum/profil",
               json={"pseudo": "Alice", "groupe": 4, "pseudo_public": True,
                     "groupe_public": True}, headers=auth("alice"))
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
    from routers.soumission import JOB_RE
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
                   json={"pseudo": "", "groupe": None, "pseudo_public": True,
                         "groupe_public": True}, headers=auth("alice"))
        assert r.status_code == 200, (r.status_code, r.text)
        profil = base.profils["sub-alice"]
        assert profil["pseudo_public"] is False, profil
        assert profil["groupe_public"] is False, profil


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


def test_theme_inconnu_est_refuse():
    """`etat.THEMES` est la liste close, et elle est vérifiée avant d'écrire."""
    with contexte(jetons={"alice": "sub-alice"}) as (c, base, _tmp):
        for mauvais in ("", "sepia", "DARK", "light; DROP TABLE"):
            r = c.put("/preferences", json={"theme": mauvais},
                      headers=auth("alice"))
            assert r.status_code == 400, (mauvais, r.status_code)
        assert not base.themes, base.themes


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
        accorde = [t for t in base.xp.values() if t["montant"] > 0]
        assert len(accorde) == 1, base.xp


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
        assert base.etats[("sub-alice", "tp2-ex3")] == "essaye", base.etats


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
        assert c.get("/r/" + premier).json() == {"state": "queued", "position": 1}
        assert c.get("/r/" + second).json() == {"state": "queued", "position": 2}
        # Le worker prend le premier : il n'est plus « 1er dans la file ».
        open(os.path.join(config.SPOOL, premier, ".lock"), "w").close()
        assert c.get("/r/" + premier).json() == {"state": "running"}
        r = c.get("/r/" + "a" * 32)
        assert r.status_code == 404 and r.json() == {"state": "gone"}, r.text


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        fn()
        print("ok   " + fn.__name__)
    print("\n%d vérifications passées." % len(tests))
