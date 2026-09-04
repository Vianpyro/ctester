#!/usr/bin/env python3
"""La v1 et la v2 répondent-elles la MÊME chose ? Le contrôle de non-régression.

    python3 test_parite.py

Ni `test_ctester.py` ni `test_api.py` ne peuvent répondre à cette question : le
premier éprouve la v1, le second la v2, et deux suites vertes séparément peuvent
décrire deux comportements différents. Ce fichier-ci envoie LA MÊME série de
requêtes aux deux implémentations, dans le même ordre, contre deux bases
simulées identiques, et compare code par code et corps par corps.

C'est le seul contrôle qui rende la bascule vérifiable AVANT de la faire.

CE QU'IL NE COUVRE PAS, ET QUI EST DIT ICI PLUTÔT QUE DEVINÉ : les différences
DÉLIBÉRÉES sont listées dans `ECARTS_ASSUMES`, avec leur raison. Toute autre
différence fait échouer ce fichier. Une liste vide serait plus jolie et moins
honnête -- la migration en a produit trois, et les cacher dans une
normalisation trop large ferait passer la prochaine, qui ne serait pas voulue.

Il DISPARAÎT avec la v1 (étape 6) : il n'a plus rien à comparer.
"""

import gzip
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "app")]

os.environ.setdefault("CTESTER_ORIGINS",
                      "https://tch009.thevhome.com,https://vianpyro.github.io")

try:
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover
    sys.exit("test_parite.py a besoin de httpx2 : pip install -r requirements-dev.txt")

import app        # noqa: E402  -- la v1, telle qu'elle est déployée
import config     # noqa: E402
import deps       # noqa: E402
import etat       # noqa: E402
import main       # noqa: E402
import security   # noqa: E402
from services import quotas  # noqa: E402
from test_api import CATALOGUE, BaseSimulee, _modules_avec_etat  # noqa: E402

CONNUE = "https://tch009.thevhome.com"
CLE = "cle-de-session"
# LA VRAIE PAGE DU DÉPÔT, PAS UNE MAQUETTE. `web2` sert la page comme `web` --
# `tch009.thevhome.com` sert les deux depuis ce Dell -- donc la bascule NPM la
# fait passer par la v2 aussi. La comparer sur un faux `index.html` ne dirait
# rien de la CSP, qui est calculée sur le document réel.
PAGE = os.path.join(HERE, "web")
JETONS = {"alice": "sub-alice", "prof": "sub-prof"}

# --- Les écarts VOULUS ------------------------------------------------------
# Chacun est une décision, pas un oubli. Le format est
# (méthode, chemin) -> raison ; le contrôle vérifie alors seulement que les DEUX
# répondent une erreur du même ORDRE (4xx contre 4xx), pas le même texte.
ECARTS_ASSUMES = {
    ("POST", "/submit", "corps trop gros"): (
        "La borne de corps est passée du début de chaque handler au middleware, "
        "donc un seul message pour toutes les routes. La v1 disait « soumission "
        "trop grosse ou vide » sur /submit et « corps trop gros ou vide » "
        "ailleurs ; la v2 dit le second partout. Même code (413), même effet."),
    ("POST", "/forum", "texte non textuel"): (
        "Pydantic refuse un `texte` qui n'est pas une chaîne AVANT que "
        "`forum_texte()` ne le voie : 400 « requête malformée » au lieu de 400 "
        "« un message vide n'aide personne ». Même code, message plus juste."),
    ("PUT", "/etat", "statut non textuel"): (
        "Même raison : un `statut` numérique est refusé par le schéma avant "
        "d'atteindre la comparaison avec `etat.STATUSES`."),
    ("POST", "/submit", "clé absente"): (
        "AMÉLIORATION VOULUE. La v1 répondait 400 « requête malformée » quand "
        "la clé MANQUAIT et 403 quand elle était FAUSSE : la différence disait "
        "à qui sonde s'il avait la bonne forme de requête. La v2 répond 403 "
        "dans les deux cas -- une clé absente EST une clé invalide."),
}


def _decomprimer(corps, entetes):
    """`httpx` décompresse tout seul, `urllib` non. On aligne le second."""
    if entetes.get("Content-Encoding") == "gzip" and corps:
        return gzip.decompress(corps)
    return corps


def _catalogue(racine):
    static = os.path.join(racine, "app")
    for sous in ("", "tp", "quiz"):
        os.makedirs(os.path.join(static, sous), exist_ok=True)
    with open(os.path.join(static, "tps.json"), "w", encoding="utf-8") as fh:
        json.dump(CATALOGUE, fh)
    with open(os.path.join(static, "tp", "tp2-ex3.json"), "w",
              encoding="utf-8") as fh:
        json.dump({"consigne": "Additionne."}, fh)
    with open(os.path.join(static, "quiz", "quiz1.json"), "w",
              encoding="utf-8") as fh:
        json.dump({"questions": [{"id": "q1", "text": "2+2 ?"}]}, fh)
    return static


class Client1:
    """La v1, derrière un vrai `ThreadingHTTPServer` -- pas un client de test.

    C'est le point : on interroge le serveur tel que le Dell le fait tourner,
    sockets comprises, pour que la comparaison porte sur ce que le navigateur
    reçoit et pas sur ce que le code croit renvoyer.
    """

    def __init__(self, racine, base):
        self.static = _catalogue(racine)
        self.spool = os.path.join(racine, "spool")
        os.makedirs(self.spool, exist_ok=True)
        self.garde = (app.etat, app.current_user, app.current_name, app.STATIC,
                      app.SPOOL, app.PAGE, app.KEY, app.OIDC_ISSUER,
                      app.OIDC_CLIENT_ID, app.FORUM_MODERATORS,
                      app.FORUM_GROUPES, app.Handler.quota,
                      app.Handler.state_quota, app.Handler.forum_quota,
                      app.Handler.presence)
        app.etat = base
        app.current_user = lambda e: JETONS.get(
            e.get("Authorization", "").replace("Bearer ", ""))
        app.current_name = lambda e: ""
        app.STATIC, app.SPOOL = self.static, self.spool
        app.PAGE = PAGE
        app.KEY = CLE
        app.OIDC_ISSUER = "https://auth.exemple.com"
        app.OIDC_CLIENT_ID = "ctester"
        app.FORUM_MODERATORS = frozenset({"sub-prof"})
        app.FORUM_GROUPES = (4, 6)
        app.Handler.quota = quotas.Quota(cooldown=0, hourly=100000)
        app.Handler.state_quota = quotas.Quota(cooldown=0, hourly=100000)
        app.Handler.forum_quota = quotas.Quota(cooldown=0, hourly=100000)
        app.Handler.presence = quotas.Presence()
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base_url = "http://127.0.0.1:%d" % self.srv.server_address[1]

    def appel(self, methode, chemin, corps=None, entetes=None):
        charge = json.dumps(corps).encode() if corps is not None else None
        requete = urllib.request.Request(self.base_url + chemin, data=charge,
                                         method=methode)
        requete.add_header("Origin", CONNUE)
        # LE MÊME `Accept-Encoding` DES DEUX CÔTÉS, sinon la comparaison est
        # fausse : `urllib` n'en envoie aucun et `httpx` demande gzip, donc l'un
        # recevrait le fichier nu et l'autre la version compressée -- deux
        # étiquettes différentes (`-gz`) pour un comportement identique.
        requete.add_header("Accept-Encoding", "gzip")
        if charge is not None:
            requete.add_header("Content-Type", "application/json")
        for cle, valeur in (entetes or {}).items():
            requete.add_header(cle, valeur)
        try:
            with urllib.request.urlopen(requete) as reponse:
                return (reponse.status, _decomprimer(reponse.read(),
                                                     reponse.headers),
                        dict(reponse.headers))
        except urllib.error.HTTPError as err:
            return err.code, _decomprimer(err.read(), err.headers), dict(err.headers)

    def fermer(self):
        self.srv.shutdown()
        self.srv.server_close()
        (app.etat, app.current_user, app.current_name, app.STATIC, app.SPOOL,
         app.PAGE, app.KEY, app.OIDC_ISSUER, app.OIDC_CLIENT_ID,
         app.FORUM_MODERATORS, app.FORUM_GROUPES, app.Handler.quota,
         app.Handler.state_quota, app.Handler.forum_quota,
         app.Handler.presence) = self.garde


class Client2:
    """La v2, par `TestClient` -- le même code ASGI que sert uvicorn."""

    def __init__(self, racine, base):
        self.static = _catalogue(racine)
        self.spool = os.path.join(racine, "spool")
        os.makedirs(self.spool, exist_ok=True)
        self.modules = _modules_avec_etat()
        self.garde_etat = [(m, m.etat) for m in self.modules]
        self.garde_config = {n: getattr(config, n) for n in
                             ("STATIC", "SPOOL", "PAGE", "KEY", "OIDC_ISSUER",
                              "OIDC_CLIENT_ID", "FORUM_MODERATORS",
                              "FORUM_GROUPES")}
        self.garde_secu = (security.current_user, security.current_name)
        self.garde_quotas = (deps.quota, deps.state_quota, deps.forum_quota,
                             deps.presence)
        for m in self.modules:
            m.etat = base
        config.STATIC, config.SPOOL, config.PAGE = self.static, self.spool, PAGE
        config.KEY = CLE
        config.OIDC_ISSUER = "https://auth.exemple.com"
        config.OIDC_CLIENT_ID = "ctester"
        config.FORUM_MODERATORS = frozenset({"sub-prof"})
        config.FORUM_GROUPES = (4, 6)
        security.current_user = lambda e: JETONS.get(
            e.get("Authorization", "").replace("Bearer ", ""))
        security.current_name = lambda e: ""
        deps.quota = quotas.Quota(cooldown=0, hourly=100000)
        deps.state_quota = quotas.Quota(cooldown=0, hourly=100000)
        deps.forum_quota = quotas.Quota(cooldown=0, hourly=100000)
        deps.presence = quotas.Presence()
        self.client = TestClient(main.create_app())

    def appel(self, methode, chemin, corps=None, entetes=None):
        tous = {"Origin": CONNUE, "Accept-Encoding": "gzip"}
        tous.update(entetes or {})
        r = self.client.request(methode, chemin, json=corps, headers=tous)
        return r.status_code, r.content, dict(r.headers)

    def fermer(self):
        for m, ancien in self.garde_etat:
            m.etat = ancien
        for nom, valeur in self.garde_config.items():
            setattr(config, nom, valeur)
        security.current_user, security.current_name = self.garde_secu
        (deps.quota, deps.state_quota, deps.forum_quota,
         deps.presence) = self.garde_quotas


_HEX32 = re.compile(r"\A[0-9a-f]{32}\Z")


def normaliser(corps):
    """Ce qui DOIT différer entre deux exécutions, et rien de plus.

    ON COMPARE LE JSON ANALYSÉ, PAS LES OCTETS. La v1 sérialise avec le
    `json.dumps` de la bibliothèque standard (espaces après les deux-points,
    `ensure_ascii`, donc `\u00e9`) ; Starlette sérialise compact en UTF-8. Les
    deux corps sont le MÊME objet, et un navigateur ne fait pas la différence --
    comparer les octets ferait échouer ce fichier sur cinquante non-écarts et
    noierait le seul vrai.

    Les identifiants de job et de message sont des uuid4 : ils sont remplacés,
    parce que c'est la seule chose qui a le droit de ne pas être identique.
    """
    try:
        return _masquer(json.loads(corps or b"null"))
    except ValueError:
        # Pas du JSON (un fichier servi) : les octets, alors, tels quels.
        return corps or b""


def _masquer(valeur):
    """Remplace récursivement tout uuid4 hexadécimal par `<id>`."""
    if isinstance(valeur, dict):
        return {k: _masquer(v) for k, v in valeur.items()}
    if isinstance(valeur, list):
        return [_masquer(v) for v in valeur]
    if isinstance(valeur, str) and _HEX32.match(valeur):
        return "<id>"
    return valeur


# La série. Chaque entrée est (nom lisible, méthode, chemin, corps, en-têtes).
def _requetes():
    auth_a = {"Authorization": "Bearer alice"}
    auth_p = {"Authorization": "Bearer prof"}
    anon = {}
    code = {"submission.c": "int main(){return 0;}"}
    return [
        # -- anonyme
        ("healthz", "GET", "/healthz", None, anon),
        ("oidc", "GET", "/oidc.json", None, anon),
        ("catalogue", "GET", "/tps.json", None, anon),
        ("consigne", "GET", "/tp/tp2-ex3.json", None, anon),
        ("consigne inconnue", "GET", "/tp/nexistepas.json", None, anon),
        ("quiz", "GET", "/quiz/quiz1.json", None, anon),
        ("quiz sur un exo de code", "GET", "/quiz/tp2-ex3.json", None, anon),
        ("route inconnue", "GET", "/pas-une-route", None, anon),
        ("verdict mal formé", "GET", "/r/pas-un-id", None, anon),
        ("verdict disparu", "GET", "/r/" + "a" * 32, None, anon),

        # -- soumission
        # (« submit sans clé » est un écart VOULU : voir ECARTS_ASSUMES.)
        ("submit mauvaise clé", "POST", "/submit",
         {"key": "non", "tp": "tp2-ex3", "files": code}, anon),
        ("submit TP inconnu", "POST", "/submit",
         {"key": CLE, "tp": "nexistepas", "files": code}, anon),
        ("submit fichier inattendu", "POST", "/submit",
         {"key": CLE, "tp": "tp2-ex3", "files": {"autre.c": "x"}}, anon),
        ("submit vide", "POST", "/submit",
         {"key": CLE, "tp": "tp2-ex3", "files": {"submission.c": "  "}}, anon),
        ("submit ok", "POST", "/submit",
         {"key": CLE, "tp": "tp2-ex3", "files": code}, anon),
        ("submit quiz sans réponses", "POST", "/submit",
         {"key": CLE, "tp": "quiz1", "answers": {}}, anon),
        ("submit quiz ok", "POST", "/submit",
         {"key": CLE, "tp": "quiz1", "answers": {"q1": "4"}}, anon),

        # -- compte, sans jeton puis avec
        ("etats anonyme", "GET", "/etats", None, anon),
        ("etats", "GET", "/etats", None, auth_a),
        ("pratique", "GET", "/pratique", None, auth_a),
        ("progres", "GET", "/progres", None, auth_a),
        ("preferences vides", "GET", "/preferences", None, auth_a),
        ("preferences thème inconnu", "PUT", "/preferences",
         {"theme": "sepia"}, auth_a),
        ("preferences ok", "PUT", "/preferences", {"theme": "dark"}, auth_a),
        ("preferences relues", "GET", "/preferences", None, auth_a),
        ("brouillon TP inconnu", "GET", "/brouillon?ex=nexistepas", None, auth_a),
        ("brouillon absent", "GET", "/brouillon?ex=tp2-ex3", None, auth_a),
        ("brouillon écrit", "PUT", "/brouillon",
         {"tp": "tp2-ex3", "files": code}, auth_a),
        ("brouillon relu", "GET", "/brouillon?ex=tp2-ex3", None, auth_a),
        ("etat statut inconnu", "PUT", "/etat",
         {"tp": "tp2-ex3", "files": code, "statut": "presque"}, auth_a),
        ("etat ok", "PUT", "/etat",
         {"tp": "tp2-ex3", "files": code, "statut": "valide"}, auth_a),

        # -- forum
        ("forum anonyme", "GET", "/forum?ex=tp2-ex3", None, anon),
        ("forum TP inconnu", "GET", "/forum?ex=nexistepas", None, auth_a),
        ("forum vide", "GET", "/forum?ex=tp2-ex3", None, auth_a),
        ("forum message vide", "POST", "/forum",
         {"tp": "tp2-ex3", "texte": "   "}, auth_a),
        ("forum message trop long", "POST", "/forum",
         {"tp": "tp2-ex3", "texte": "a" * 5000}, auth_a),
        ("forum publier", "POST", "/forum",
         {"tp": "tp2-ex3", "texte": "une question"}, auth_a),
        ("forum fil peuplé", "GET", "/forum?ex=tp2-ex3", None, auth_a),
        ("forum fil vu du prof", "GET", "/forum?ex=tp2-ex3", None, auth_p),
        ("forum supprimer id invalide", "DELETE", "/forum?id=xx", None, auth_a),
        ("forum supprimer absent", "DELETE", "/forum?id=" + "b" * 32, None, auth_a),
        ("forum signaler id invalide", "POST", "/forum/signalement",
         {"id": "zz"}, auth_a),
        ("forum modération refusée", "GET", "/forum/moderation", None, auth_a),
        ("forum modération", "GET", "/forum/moderation", None, auth_p),
        ("forum modérer action inconnue", "POST", "/forum/moderation",
         {"id": "c" * 32, "action": "brûler"}, auth_p),
        ("forum modérer message absent", "POST", "/forum/moderation",
         {"id": "c" * 32, "action": "masquer"}, auth_p),
        ("forum profil", "GET", "/forum/profil", None, auth_a),
        ("forum profil nom réservé", "POST", "/forum/profil",
         {"pseudo": "Enseignant"}, auth_a),
        ("forum profil groupe hors liste", "POST", "/forum/profil",
         {"pseudo": "Alice", "groupe": 7}, auth_a),
        ("forum profil ok", "POST", "/forum/profil",
         {"pseudo": "Alice", "groupe": 4, "pseudo_public": True,
          "groupe_public": True}, auth_a),
        ("forum profil relu", "GET", "/forum/profil", None, auth_a),
        ("forum fil avec un nom", "GET", "/forum?ex=tp2-ex3", None, auth_p),

        # -- la page, servie par les deux le temps de la bascule
        ("page /", "GET", "/", None, anon),
        ("page /index.html", "GET", "/index.html", None, anon),
        ("page style", "GET", "/style.css", None, anon),
        ("page config.js", "GET", "/config.js", None, anon),
        ("page app.js", "GET", "/app.js", None, anon),
        ("page vendor", "GET", "/vendor/purify-3.4.14.min.js", None, anon),
        ("page fichier hors liste", "GET", "/secret.txt", None, anon),
        ("page HEAD /", "HEAD", "/", None, anon),

        # -- effacement, en dernier
        ("moi", "DELETE", "/moi", None, auth_a),
    ]


def test_parite_des_reponses():
    """La v1 et la v2 répondent le même code et le même corps, requête par requête."""
    racine1, racine2 = tempfile.mkdtemp(), tempfile.mkdtemp()
    base1, base2 = BaseSimulee(), BaseSimulee()
    v1 = Client1(racine1, base1)
    v2 = Client2(racine2, base2)
    ecarts = []
    try:
        for nom, methode, chemin, corps, entetes in _requetes():
            c1, b1, h1 = v1.appel(methode, chemin, corps, entetes)
            c2, b2, h2 = v2.appel(methode, chemin, corps, entetes)
            if c1 != c2 or normaliser(b1) != normaliser(b2):
                ecarts.append((nom, methode, chemin, c1, b1[:300], c2, b2[:300]))
            # Les en-têtes qui comptent pour un navigateur, sur CHAQUE réponse.
            for entete in ("access-control-allow-origin", "vary",
                           "cache-control", "content-type", "etag",
                           "content-encoding", "content-security-policy"):
                v_1 = {k.lower(): v for k, v in h1.items()}.get(entete)
                v_2 = {k.lower(): v for k, v in h2.items()}.get(entete)
                if v_1 != v_2:
                    ecarts.append((nom + " [" + entete + "]", methode, chemin,
                                   c1, v_1, c2, v_2))
    finally:
        v2.fermer()
        v1.fermer()
        shutil.rmtree(racine1, ignore_errors=True)
        shutil.rmtree(racine2, ignore_errors=True)

    if ecarts:
        lignes = ["%d écart(s) entre la v1 et la v2 :" % len(ecarts), ""]
        for nom, methode, chemin, c1, b1, c2, b2 in ecarts:
            lignes += ["  %s  (%s %s)" % (nom, methode, chemin),
                       "      v1 -> %s %r" % (c1, b1),
                       "      v2 -> %s %r" % (c2, b2), ""]
        raise AssertionError("\n".join(lignes))


def test_ecarts_assumes_restent_du_meme_ordre():
    """Les trois différences VOULUES gardent le même code de statut.

    Un écart assumé sur le message est une chose ; un écart sur le code en est
    une autre -- la page branche dessus (401 relance la connexion, 413 dit de
    raccourcir, 429 attend). Ce contrôle épingle donc les codes des deux côtés :
    si l'un bouge, il faut le décider, pas le découvrir en production.

    IL VÉRIFIE AUSSI QUE L'ÉCART EXISTE ENCORE. Le jour où les deux réponses
    redeviennent identiques, l'entrée correspondante de `ECARTS_ASSUMES` est
    devenue du folklore et doit être retirée -- sinon la liste finit par
    excuser des différences que plus personne n'a choisies.
    """
    racine1, racine2 = tempfile.mkdtemp(), tempfile.mkdtemp()
    v1 = Client1(racine1, BaseSimulee())
    v2 = Client2(racine2, BaseSimulee())
    auth_a = {"Authorization": "Bearer alice"}
    try:
        gros = {"key": CLE, "tp": "tp2-ex3",
                "files": {"submission.c": "a" * (config.MAX_CODE + 8192)}}
        cas = [
            # (clé, méthode, chemin, corps, en-têtes, code v1, code v2)
            (("POST", "/submit", "corps trop gros"), "POST", "/submit", gros,
             {}, 413, 413),
            (("POST", "/forum", "texte non textuel"), "POST", "/forum",
             {"tp": "tp2-ex3", "texte": 42}, auth_a, 400, 400),
            (("PUT", "/etat", "statut non textuel"), "PUT", "/etat",
             {"tp": "tp2-ex3", "files": {"submission.c": "x"}, "statut": 7},
             auth_a, 400, 400),
            # LE SEUL ÉCART DE CODE, et il resserre : une clé absente ne se
            # distingue plus d'une clé fausse.
            (("POST", "/submit", "clé absente"), "POST", "/submit",
             {"tp": "tp2-ex3", "files": {"submission.c": "x"}}, {}, 400, 403),
        ]
        assert len(cas) == len(ECARTS_ASSUMES), "un écart n'est pas éprouvé"
        for cle, methode, chemin, corps, entetes, attendu1, attendu2 in cas:
            assert cle in ECARTS_ASSUMES, cle
            c1, b1, _ = v1.appel(methode, chemin, corps, entetes)
            c2, b2, _ = v2.appel(methode, chemin, corps, entetes)
            assert (c1, c2) == (attendu1, attendu2), (cle, c1, b1, c2, b2)
            assert normaliser(b1) != normaliser(b2), (
                cle, "l'écart a disparu : retirer son entrée de ECARTS_ASSUMES")
    finally:
        v2.fermer()
        v1.fermer()
        shutil.rmtree(racine1, ignore_errors=True)
        shutil.rmtree(racine2, ignore_errors=True)


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        fn()
        print("ok   " + fn.__name__)
    print("\n%d vérifications passées." % len(tests))
