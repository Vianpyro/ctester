"""ctester -- les en-têtes de sortie : CORS, `Vary`, cache, CSP, ETag.

TOUT CE QUI DOIT APPARAÎTRE SUR *CHAQUE* RÉPONSE EST ICI, dans un middleware
unique. C'est la même leçon que le `end_headers()` de la version précédente : les
réponses partent de partout -- une route, un gestionnaire d'exception, un 304,
un 404 de Starlette que personne n'a écrit -- et une réponse sans en-tête CORS
est une panne invisible côté serveur : seul le navigateur de l'étudiant la voit.

PAS `CORSMiddleware` de Starlette, et c'est délibéré :
  * il répond 400 à un préflight d'origine inconnue, là où on veut ne rien
    poser du tout et laisser le navigateur bloquer -- un réglage oublié ne doit
    pas ressembler à une panne de service ;
  * il ajoute une SECONDE ligne `Vary` au lieu de fusionner. Deux lignes `Vary`
    séparées sont légales mais mal recombinées par certains caches, et un cache
    qui perd `Origin` sert la réponse d'une origine à une autre.
"""

import gzip
import hashlib
import os

import csp as politique_csp
from starlette.datastructures import MutableHeaders
from starlette.responses import JSONResponse, Response

import config

# Le préflight, pour toute route. `Max-Age` à 86400 est ce qui empêche la
# séparation front/back de coûter un aller-retour de plus par requête : sans
# lui, chaque PUT et chaque DELETE en paierait un.
#
# DELETE EST DANS LA LISTE ET DOIT Y RESTER -- `compte.js` supprime un compte,
# `forum.js` un message. L'oubli ne casse que le cross-origin, c'est-à-dire
# seulement la production, et seulement ces deux boutons-là.
PREFLIGHT = {
    "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
    "Access-Control-Allow-Headers": "Authorization, Content-Type",
    "Access-Control-Max-Age": "86400",
}


class EnTetes:
    """Middleware ASGI : CORS, `Vary`, et `no-store` par défaut.

    ASGI PUR ET PAS `BaseHTTPMiddleware` : celui-ci met la réponse en mémoire
    tampon et enveloppe les exceptions, ce qui change le code de sortie de
    routes qui en dépendent. Ici on ne fait que réécrire l'en-tête de départ.

    `no-store` EST LE DÉFAUT, et l'exception est explicite. Toute réponse de
    données -- verdict, progression, forum, préférences -- ne doit pas être
    gardée ; les fichiers posent `no-cache` eux-mêmes (voir `fichier()`), et ce
    sont les seuls. Un défaut dans l'autre sens ferait qu'une route de compte
    ajoutée un soir de session serait mise en cache sans que personne ne le
    demande.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        origine = ""
        for nom, valeur in scope["headers"]:
            if nom == b"origin":
                origine = valeur.decode("latin-1").strip().rstrip("/")
                break
        connue = bool(origine) and origine in config.ORIGINS

        async def envoyer(message):
            if message["type"] == "http.response.start":
                entetes = MutableHeaders(scope=message)
                if connue:
                    entetes["Access-Control-Allow-Origin"] = origine
                # PAS de `Access-Control-Allow-Credentials` : il n'y a aucun
                # cookie ici, le jeton voyage en en-tête `Authorization`.
                #
                # UN SEUL EN-TÊTE `Vary`, et il annonce les deux axes.
                # L'affectation remplace ce qui s'y trouvait déjà -- c'est le
                # point : deux lignes ne doivent pas pouvoir cohabiter.
                # `Accept-Encoding` y reste même sur les réponses non
                # compressées : la constante est juste partout, une valeur
                # calculée serait un `if` de plus sur chaque réponse.
                entetes["Vary"] = "Accept-Encoding, Origin"
                if "cache-control" not in entetes:
                    entetes["Cache-Control"] = "no-store"
            await send(message)

        # LA BORNE DE CORPS EST ICI, AVANT TOUTE ANALYSE, et pour toute route.
        # Uvicorn N'A PAS de limite de taille de corps : sans ce test, un POST
        # annonçant 2 Go ferait lire 2 Go avant que la moindre validation ne
        # s'exécute. Le poser une fois ici, plutôt qu'au début de chaque
        # routeur, est ce qui garantit qu'une route ajoutée un soir de séance
        # naît bornée.
        if scope["method"] in ("POST", "PUT"):
            trop = _corps_hors_bornes(scope)
            if trop:
                await _repondre(envoyer, 413,
                                b'{"error": "corps trop gros ou vide"}')
                return

        # LE PRÉFLIGHT NE PASSE PAS PAR LE ROUTEUR, et c'est ce qui le rend
        # correct. Une route attrape-tout `OPTIONS /{chemin:path}` ferait
        # répondre 405 à tout chemin INCONNU : Starlette retient la
        # correspondance partielle (bon chemin, mauvaise méthode) de cette
        # route-là et ne descend jamais jusqu'à son 404. Un `/nimporte` se
        # mettrait alors à répondre « méthode non autorisée », ce qui est faux
        # et ce qui confirme au passage qu'il existe.
        if scope["method"] == "OPTIONS":
            await _repondre(envoyer, 204, b"", PREFLIGHT)
            return

        await self.app(scope, receive, envoyer)


def _corps_hors_bornes(scope):
    """True si `Content-Length` manque, est illisible, ou sort des bornes.

    Absent vaut « hors bornes » : une requête en `chunked` n'annonce pas sa
    taille, et on ne lit pas un corps dont on ignore la longueur.
    """
    brut = b""
    for nom, valeur in scope["headers"]:
        if nom == b"content-length":
            brut = valeur
            break
    try:
        longueur = int(brut)
    except ValueError:
        return True
    return not 0 < longueur <= config.MAX_CODE + 4096


async def _repondre(envoyer, code, corps, entetes=None):
    """Une réponse complète depuis le middleware, sans passer par le routeur."""
    lignes = [(b"content-length", str(len(corps)).encode())]
    if corps:
        lignes.append((b"content-type", b"application/json; charset=utf-8"))
    lignes += [(k.lower().encode(), v.encode())
               for k, v in (entetes or {}).items()]
    await envoyer({"type": "http.response.start", "status": code,
                   "headers": lignes})
    await envoyer({"type": "http.response.body", "body": corps})


class JSON(JSONResponse):
    """`application/json; charset=utf-8`, comme la version précédente.

    Starlette rend `application/json` tout court -- correct au sens de la RFC
    8259 (JSON est toujours de l'UTF-8), mais ce n'est pas ce que ce service a
    toujours annoncé. Le `charset` explicite coûte quinze octets par réponse et
    évite d'avoir à se demander, le jour d'une panne, si un intermédiaire
    (Cloudflare, un cache, un proxy d'école) traite les deux pareil.

    Posée en `default_response_class` : toutes les routes qui rendent un `dict`
    passent par ici, sans qu'aucune n'ait à y penser.
    """

    media_type = "application/json; charset=utf-8"


def erreur(code, message, cle="error", **extra):
    """Le corps d'erreur que la page attend : `{"error": "..."}`, et rien d'autre.

    UNE SEULE FORME, parce que `app.js` lit `out.error` et affiche ce qu'il y
    trouve. `cle` n'existe que pour le sondage de verdict, qui répond
    `{"state": ...}` ; `extra` porte `retry_after` sur un 429, dont la page se
    sert pour dire combien de temps attendre au lieu d'inviter à recliquer.
    """
    return JSON(dict({cle: message}, **extra), status_code=code)


def fichier(request, body, ctype, issuer=""):
    """Un fichier statique, revalidé à chaque visite, transféré si besoin.

    `no-cache` NE VEUT PAS DIRE « ne pas mettre en cache » : il veut dire
    « garde-le, mais redemande-moi avant de t'en servir ». Le navigateur repasse
    donc systématiquement, et un correctif déployé se voit toujours tout de
    suite -- c'est ce que `no-store` protégeait, et c'est intact. Ce qui change,
    c'est qu'un fichier inchangé revient en 304 vide au lieu de repartir en
    entier : la page, sa feuille et son script font 65 Ko, et un étudiant
    recharge beaucoup.

    `no-store` interdisait AUSSI le cache aller-retour du navigateur (bfcache) :
    avec lui, le bouton Retour refaisait toute la page.
    """
    etiquette = '"' + hashlib.sha256(body).hexdigest()[:16]
    # LA CSP EST CALCULÉE SUR LE CORPS EN CLAIR, avant la compression : la
    # politique porte sur le document, pas sur son transport.
    politique = politique_csp.csp(body, issuer) if ctype.startswith("text/html") else ""
    # UNE ÉTIQUETTE PAR REPRÉSENTATION. Deux corps différents pour une même URL
    # -- l'original et le gzip -- ne peuvent pas partager un ETag : un cache
    # intermédiaire servirait l'un en croyant valider l'autre.
    comprime = (len(body) >= 1024
                and "gzip" in request.headers.get("accept-encoding", ""))
    if comprime:
        body = gzip.compress(body, 6)
        etiquette += "-gz"
    etiquette += '"'

    entetes = {"ETag": etiquette, "Cache-Control": "no-cache"}
    # SUR LE 304 AUSSI. Le navigateur rejoue la réponse gardée en la mettant à
    # jour avec ces en-têtes ; une CSP qui n'apparaîtrait que sur le 200
    # disparaîtrait donc dès la deuxième visite, c'est-à-dire presque toujours.
    if politique:
        entetes["Content-Security-Policy"] = politique

    if request.headers.get("if-none-match") == etiquette:
        return Response(status_code=304, headers=entetes)
    if comprime:
        entetes["Content-Encoding"] = "gzip"
    return Response(body, media_type=ctype, headers=entetes)


def fichier_du_disque(request, base, nom, ctype, issuer=""):
    """Un fichier du disque, et `base` DIT LEQUEL DES DEUX RÉPERTOIRES.

    Pas de défaut, exprès : la page (`config.PAGE`) et la release publiée par
    le worker (`config.PUBLISHED`) vivent à part depuis que `web/` est destiné à
    GitHub Pages, et les deux passent par ici. Un défaut ferait chercher
    `exercises/<id>.json` dans le répertoire de la page -- un 500 sur chaque
    consigne et chaque quiz, en production seulement, parce qu'un harnais qui
    monte les deux au même endroit ne peut pas le voir.

    `nom` NE VIENT JAMAIS DE L'URL telle quelle : les appelants le
    reconstruisent depuis le catalogue ou depuis une liste close. Il n'y a donc
    pas de chemin à traverser, et pas de `..` à filtrer -- filtrer voudrait dire
    qu'on accepte une entrée, ce qu'on ne fait pas.
    """
    try:
        with open(os.path.join(base, nom), "rb") as fh:
            corps = fh.read()
    except OSError:
        return erreur(500, "fichier manquant")
    return fichier(request, corps, ctype, issuer)
