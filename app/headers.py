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
import re

from starlette.datastructures import MutableHeaders
from starlette.responses import JSONResponse, Response

import config

# AUCUN SCRIPT INLINE DANS LA PAGE, donc aucun hachage à tenir à jour. C'est ce
# qui permet à la même politique de tenir dans un en-tête ici ET dans le
# `<meta>` de `index.html`, que GitHub Pages sert sans pouvoir poser d'en-tête.
# Le bootstrap du thème vit dans `web/config.js`, chargé en tête de `<head>`
# sans `defer` : il tourne donc avant le premier rendu, comme l'inline qu'il
# remplace. Un inline rajouté par distraction est alors bloqué bruyamment, au
# lieu de passer par un hachage recopié qui se périme en silence.
_INLINE_SCRIPT_RE = re.compile(rb"<script(?![^>]*\ssrc=)[^>]*>(.*?)</script>",
                               re.DOTALL)

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


def csp(body, issuer=""):
    """La politique de sécurité du contenu pour CE document HTML.

    ELLE DOIT DIRE LA MÊME CHOSE QUE LE `<meta>` de `index.html`, à
    `frame-ancestors` près : un `<meta>` ne peut pas le porter, et c'est la
    seule perte réelle du passage à GitHub Pages (à reposer par une Transform
    Rule Cloudflare, `X-Frame-Options: DENY`). Ici il reste, ce serveur pouvant
    poser des en-têtes.

    `style-src` garde `'unsafe-inline'` : la page pose des attributs `style`
    calculés (la largeur d'une jauge, le rang d'une coche de verdict). Ce sont
    des styles, pas des scripts, et les retirer demanderait de réécrire trois
    composants pour un gain nul face à la menace visée ici.

    `connect-src` doit contenir l'émetteur OIDC : `compte.js` va y chercher le
    document de découverte puis le jeton. Sans lui, la connexion échoue en
    silence -- et c'est le genre de panne qu'une CSP produit sans le dire. Il
    doit aussi contenir l'API : pendant la bascule, ce serveur sert encore la
    page alors que `config.js` appelle déjà `tch099`.

    `body` N'EST PLUS LU QUE POUR REFUSER UN SCRIPT INLINE. La page n'en a plus
    aucun ; un qui reviendrait ne serait pas haché en douce, il ferait échouer
    `test_csp_du_document`.
    """
    if any(bloc.strip() for bloc in _INLINE_SCRIPT_RE.findall(body)):
        raise ValueError(
            "un <script> inline est apparu dans la page : `script-src 'self'` "
            "le bloque, ici comme dans le <meta> servi par GitHub Pages. "
            "Sortir le code dans un fichier, comme web/config.js.")
    origines = [o for o in (config.API_ORIGIN,) if o]
    if issuer.startswith("https://"):
        origines.append("/".join(issuer.split("/")[:3]))
    return "; ".join([
        "default-src 'none'",
        "script-src 'self'",
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self'",
        " ".join(["connect-src 'self'"] + origines),
        "base-uri 'none'",
        "form-action 'none'",
        "frame-ancestors 'none'",
    ])


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

        # LE PRÉFLIGHT NE PASSE PAS PAR LE ROUTEUR, et c'est ce qui le rend
        # correct. Une route attrape-tout `OPTIONS /{chemin:path}` ferait
        # répondre 405 à tout chemin INCONNU : Starlette retient la
        # correspondance partielle (bon chemin, mauvaise méthode) de cette
        # route-là et ne descend jamais jusqu'à son 404. Un `/nimporte` se
        # mettrait alors à répondre « méthode non autorisée », ce qui est faux
        # et ce qui confirme au passage qu'il existe.
        if scope["method"] == "OPTIONS":
            await envoyer({"type": "http.response.start", "status": 204,
                           "headers": [(k.lower().encode(), v.encode())
                                       for k, v in PREFLIGHT.items()]})
            await envoyer({"type": "http.response.body", "body": b""})
            return

        await self.app(scope, receive, envoyer)


def erreur(code, message, cle="error"):
    """Le corps d'erreur que la page attend : `{"error": "..."}`, et rien d'autre.

    UNE SEULE FORME, parce que `app.js` lit `out.error` et affiche ce qu'il y
    trouve. `cle` n'existe que pour `_result`, qui répond `{"state": ...}`.
    """
    return JSONResponse({cle: message}, status_code=code)


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
    politique = csp(body, issuer) if ctype.startswith("text/html") else ""
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
