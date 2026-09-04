#!/usr/bin/env python3
"""La frontière HTTP de l'API, éprouvée par `fastapi.testclient.TestClient`.

Ce fichier reprend le rôle que `test_http_end_to_end` tenait dans
`test_ctester.py` : ce qui se voit depuis un navigateur -- codes, en-têtes,
formes de corps -- et rien d'autre. Les règles (progression, forum, catalogue)
restent éprouvées par appel direct dans `test_ctester.py`, sans serveur : une
règle qui n'a besoin d'aucun HTTP ne doit pas dépendre d'un client de test pour
être vérifiée.

    python3 test_api.py

UNE dépendance de test, `httpx` (`pip install -r requirements-dev.txt`), tirée
par `TestClient`. L'APPLICATION, elle, n'a que ce que liste `requirements.txt`.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "app")]

# AVANT D'IMPORTER `main` : `config` lit l'environnement à l'import, et ces
# valeurs sont celles que les contrôles ci-dessous supposent. Les régler après
# coup ne changerait pas ce que l'application a déjà lu.
os.environ.setdefault("CTESTER_ORIGINS",
                      "https://tch009.thevhome.com,https://vianpyro.github.io")

try:
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover -- message, pas trace
    sys.exit("test_api.py a besoin de httpx : pip install -r requirements-dev.txt")

import main  # noqa: E402

CONNUE = "https://tch009.thevhome.com"
INCONNUE = "https://mechant.example"

client = TestClient(main.app)


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

    # Aucun cookie ici : le jeton voyage en en-tête. `Allow-Credentials`
    # n'apporterait rien et obligerait à des garanties de plus.
    assert "access-control-allow-credentials" not in r.headers


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

    # Même un préflight ne s'ouvre pas à une origine inconnue.
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
    import config
    assert not config.DOCS, "CTESTER_DOCS ne doit pas être posé en production"
    for chemin in ("/openapi.json", "/docs", "/redoc"):
        assert client.get(chemin).status_code == 404, chemin


def test_no_store_par_defaut_sur_les_donnees():
    """Le défaut est `no-store` ; seuls les fichiers disent `no-cache`.

    Un défaut dans l'autre sens ferait qu'une route de compte ajoutée un soir de
    séance serait mise en cache sans que personne ne l'ait demandé.
    """
    assert client.get("/healthz").headers.get("cache-control") == "no-store"
    assert client.get("/rien").headers.get("cache-control") == "no-store"


def test_corps_malforme_ne_renvoie_pas_l_entree():
    """422 de Pydantic -> 400 `{"error": ...}`, sans recopier ce qui a été reçu.

    Le défaut de FastAPI renvoie la valeur refusée à l'expéditeur. La page n'y
    comprendrait rien (elle lit `out.error`), et un corps refusé peut contenir
    le code de quelqu'un ou un jeton mal collé.
    """
    from fastapi import FastAPI

    essai = main.create_app()

    @essai.post("/_essai")
    def _essai(charge: dict):
        return charge

    c = TestClient(essai)
    r = c.post("/_essai", content=b"[1, 2, 3]",
               headers={"Content-Type": "application/json"})
    assert r.status_code == 400, (r.status_code, r.text)
    assert r.json() == {"error": "requête malformée"}, r.json()
    assert "1" not in r.text and "2" not in r.text, r.text
    assert isinstance(essai, FastAPI)


def test_pas_d_annonce_de_version_de_serveur():
    """`Server: uvicorn` ne sert que celui qui cherche une version vulnérable.

    Le contrôle porte sur le RÉGLAGE et pas sur la réponse : `TestClient` ne
    passe pas par uvicorn, donc l'en-tête n'apparaît qu'en vrai. C'est la ligne
    `server_header=False` de `main.py` qui compte, et c'est elle qu'on lit.
    """
    with open(os.path.join(HERE, "app", "main.py"), encoding="utf-8") as fh:
        source = fh.read()
    assert "server_header=False" in source
    # Et un seul worker : quotas, présence et cache de jetons sont en mémoire de
    # processus. Deux workers, c'est chaque quota doublé en silence.
    assert "workers=1" in source


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        fn()
        print("ok   " + fn.__name__)
    print("\n%d vérifications passées." % len(tests))
