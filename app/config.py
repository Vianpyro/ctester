"""ctester -- tous les réglages, en un seul endroit.

Un déploiement se pilote par variables d'environnement, et chaque valeur porte
ici le défaut du rôle Ansible : c'est ce qui rend les contrôles exécutables sur
le contrôleur sans rien installer ni rien déployer.

IMPORTEZ LE MODULE, PAS SES NOMS : `import config` puis `config.KEY`, jamais
`from config import KEY`. Un `from ... import` fige la valeur au moment de
l'import, et les tests règlent ces constantes après coup pour éprouver un
déploiement différent de celui de la machine qui les lance. Un import figé rend
ces tests silencieusement inopérants -- ils passeraient en n'éprouvant rien.

BIBLIOTHÈQUE STANDARD, PAS `pydantic-settings` : ce sont vingt `os.environ.get`
avec un défaut. Un modèle de réglages en plus n'ajouterait ici qu'une
dépendance de plus dans le seul processus exposé à Internet.
"""

import os
import re


def _entier(nom, defaut):
    """Un entier d'environnement, ou le défaut si la valeur ne l'est pas.

    `int()` nu ferait échouer le DÉMARRAGE du conteneur sur une faute de frappe
    dans un fichier `.env` -- une variable mal tapée doit dégrader un réglage,
    pas rendre le service injoignable.
    """
    try:
        return int(os.environ.get(nom, defaut))
    except ValueError:
        return int(defaut)


# --- Système de fichiers ----------------------------------------------------
SPOOL = os.environ.get("CTESTER_SPOOL", "/spool")
# Le catalogue publié par le worker (tps.json, tp/, quiz/).
STATIC = os.environ.get("CTESTER_STATIC", "/app")
# LA PAGE VIT AILLEURS QUE LE CATALOGUE depuis que `web/` est publié à part.
# TEMPORAIRE : n'existe que le temps de la bascule vers GitHub Pages.
#
# POUR ÉTEINDRE LA PAGE, IL FAUT VIDER LA VARIABLE, PAS LA SUPPRIMER
# (`CTESTER_PAGE=` dans Compose). Absente, le défaut ci-dessous reprend la main
# et le routeur cherche `/web` dans un conteneur qui ne le monte plus : 500
# « fichier manquant » à chaque visite au lieu du 404 attendu. Vide -> le
# routeur n'est pas monté du tout, et cette origine ne répond plus que sur des
# données.
PAGE = os.environ.get("CTESTER_PAGE", "/web")

# --- Frontière HTTP ---------------------------------------------------------
# LES ORIGINES AUTORISÉES À APPELER CETTE API, jamais `*` : chaque requête
# authentifiée porte un `Authorization`, et `*` l'ouvrirait à n'importe quelle
# page du web. Une origine absente de cette liste ne reçoit AUCUN en-tête CORS
# -- le navigateur bloque alors de lui-même -- plutôt qu'un 403 : on ne
# transforme pas un réglage oublié en panne opaque côté serveur.
ORIGINS = tuple(o.strip().rstrip("/") for o in os.environ.get(
    "CTESTER_ORIGINS",
    "https://tch009.thevhome.com,https://vianpyro.github.io").split(",")
    if o.strip())

# TRANSITION : l'origine que la PAGE appelle. Ce serveur sert encore la page
# pendant la bascule, et sa CSP doit donc autoriser `connect-src` vers l'API --
# sinon la fenêtre où `tch009` est encore sur le Dell mais `config.js` pointe
# déjà `tch099` est une page morte. Disparaît avec le routeur de la page.
API_ORIGIN = os.environ.get("CTESTER_API_ORIGIN", "https://tch099.thevhome.com")

PORT = _entier("CTESTER_PORT", "8000")

# LES DEUX BIBLIOTHÈQUES DU RENDU, ÉPINGLÉES DANS LEUR NOM DE FICHIER. Elles
# vivent dans le dépôt (`web/vendor/`, voir son README) et sont servies depuis
# cette origine : la CSP dit `script-src 'self'`, donc un CDN serait bloqué, et
# c'est voulu. Monter de version demande de toucher à cette liste ET à
# `forum.js` -- une mise à jour d'assainisseur HTML ne doit pas se faire par
# accident.
VENDOR = ("vendor/marked-18.0.11.umd.js", "vendor/purify-3.4.14.min.js")

# LA DOCUMENTATION AUTOMATIQUE EST ÉTEINTE PAR DÉFAUT, et ce n'est pas de la
# pudeur. `/docs`, `/redoc` et `/openapi.json` sont publics chez FastAPI : ils
# décrivent chaque route, chaque champ et chaque borne d'une API posée sur une
# infra personnelle. Utile en développement, offert à l'inconnu en production.
DOCS = os.environ.get("CTESTER_DOCS", "") == "1"

# --- Soumissions ------------------------------------------------------------
KEY = os.environ.get("CTESTER_KEY", "")
COOLDOWN = _entier("CTESTER_COOLDOWN", "15")
HOURLY = _entier("CTESTER_HOURLY_QUOTA", "40")
QUEUE_MAX = _entier("CTESTER_QUEUE_MAX", "60")
MAX_CODE = _entier("CTESTER_MAX_CODE_BYTES", "65536")

# --- Comptes (facultatif) ---------------------------------------------------
# SE CONNECTER EST FACULTATIF, ET TOUT DOIT TENIR SANS. Sans émetteur OIDC ni
# base, `/oidc.json` répond `{}`, la page n'affiche même pas le bouton, et le
# parcours anonyme est exactement ce qu'il était. C'est la barre de non-
# régression de toute cette fonctionnalité.
OIDC_ISSUER = os.environ.get("CTESTER_OIDC_ISSUER", "").rstrip("/")
OIDC_CLIENT_ID = os.environ.get("CTESTER_OIDC_CLIENT_ID", "")
OIDC_TTL = _entier("CTESTER_OIDC_CACHE_TTL", "300")

# --- Forum d'entraide -------------------------------------------------------
# ÉTEINT PAR DÉFAUT, ET C'EST LE RÉGLAGE SÛR. Sans au moins un `sub` de
# modérateur configuré, le forum est éteint : le bouton n'apparaît pas,
# `forum.js` n'est jamais demandé, et les routes répondent 503 en le disant. Un
# forum sans personne pour le modérer est un canal de partage de solutions avec
# une charte dessus -- on ne l'ouvre pas « en attendant ».
#
# DES `sub` OIDC OPAQUES, séparés par virgule ou espace, JAMAIS un claim du
# jeton : un rôle dérivé d'un claim non vérifié se réclame depuis un compte que
# l'on contrôle.
FORUM_MODERATORS = frozenset(
    s for s in re.split(r"[,\s]+",
                        os.environ.get("CTESTER_FORUM_MODERATORS", "")) if s)
FORUM_MAX_CHARS = _entier("CTESTER_FORUM_MAX_CHARS", "1200")
FORUM_COOLDOWN = _entier("CTESTER_FORUM_COOLDOWN", "10")
FORUM_HOURLY = _entier("CTESTER_FORUM_HOURLY_QUOTA", "20")
FORUM_PSEUDO_MAX = _entier("CTESTER_FORUM_PSEUDO_MAX", "24")
# Borne de LECTURE d'un fil et de la file de modération. Un fil d'exercice à 27
# étudiants n'en approche pas ; la borne existe pour que la page ne puisse pas
# recevoir un objet sans fin le jour où quelque chose tourne mal.
FORUM_MAX_FIL = 200

# ponytail: la liste des groupes d'une session vit ici, éditée comme la
# politique. Vide => champ libre 1..99 (l'ancien comportement). La colonne
# reste `SMALLINT CHECK (1..99)` : la liste d'une session ne vit pas dans le
# schéma. Une valeur non numérique est ignorée plutôt que de tuer le démarrage.
FORUM_GROUPES = tuple(
    int(x) for x in
    os.environ.get("CTESTER_FORUM_GROUPES", "4,6").replace(",", " ").split()
    if x.lstrip("-").isdigit())

# --- Présence ---------------------------------------------------------------
PRESENCE_TTL = _entier("CTESTER_PRESENCE_TTL", "150")
