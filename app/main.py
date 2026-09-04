#!/usr/bin/env python3
"""ctester -- l'API du juge C. Fichier géré par Ansible : éditer le rôle.

Ce processus ne compile RIEN et n'exécute RIEN. Il valide une soumission,
l'écrit dans le spool, et lit le verdict qu'un worker de l'hôte y dépose. Il n'a
ni le socket Docker, ni accès au répertoire des tests -- c'est toute la raison
pour laquelle il peut être exposé à Internet.

UN SEUL WORKER, TOUJOURS, et ce n'est pas un réglage de performance. Les quotas,
le compteur de présence, le cache de jetons OIDC et la connexion unique
d'`etat.py` sont de l'état EN MÉMOIRE DE PROCESSUS. Deux workers, c'est deux
compteurs : chaque quota est doublé en silence, et le plafond de file laisse
passer deux fois ce qu'il annonce. C'est pour ça que le lancement vit ici, dans
`__main__`, et pas dans une ligne de commande de Compose que quelqu'un
recopiera un jour avec `--workers 4`. Le jour où un deuxième processus est
vraiment nécessaire, c'est Redis ou Postgres qui tient ces compteurs, pas
uvicorn.

LES ENDPOINTS SONT `def`, PAS `async def`, et c'est délibéré. Starlette exécute
alors chacun dans son threadpool, ce qui laisse `etat.py` synchrone : ses CTE
modifiantes, son `INSERT ... SELECT` dont le `WHERE` EST le contrôle d'accès et
ses GRANT de colonne sont éprouvés contre un vrai Postgres par
`test_postgres.py`. Les réécrire en SQLAlchemy async remplacerait du SQL prouvé
par du SQL à prouver, dans la seule couche où une erreur donne accès aux données
de quelqu'un d'autre.
"""

import os
import sys

import config
import deps
import headers
import security
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from routers import (catalogue, compte, forum, page, progression, sante,
                     soumission)
from starlette.exceptions import HTTPException


def create_app():
    app = FastAPI(
        title="ctester",
        # LA DOCUMENTATION AUTOMATIQUE EST ÉTEINTE SAUF DEMANDE EXPRESSE.
        # `None` retire la route, il ne la protège pas : il n'y a donc rien à
        # contourner. Voir `config.DOCS`.
        docs_url="/docs" if config.DOCS else None,
        redoc_url="/redoc" if config.DOCS else None,
        openapi_url="/openapi.json" if config.DOCS else None,
        # Le `charset=utf-8` que ce service a toujours annoncé -- voir
        # `headers.JSON`.
        default_response_class=headers.JSON,
    )
    app.add_middleware(headers.EnTetes)

    @app.exception_handler(deps.Refus)
    async def _refus(request, exc):
        """Nos propres refus : 401, 403, 429, 503, avec leur `retry_after`."""
        return headers.erreur(exc.code, exc.message, **exc.extra)

    @app.exception_handler(RequestValidationError)
    async def _validation(request, exc):
        """422 de Pydantic -> 400 `{"error": ...}`, SANS RECOPIER L'ENTRÉE.

        Le défaut de FastAPI répond 422 avec un corps qui contient la valeur
        refusée. Deux problèmes : la page lit `out.error` et n'y comprendrait
        rien, et renvoyer l'entrée à l'expéditeur est une fuite gratuite -- un
        corps refusé peut contenir le code de quelqu'un, ou un jeton mal collé.
        Le message est donc constant, et le détail reste dans le journal.
        """
        return headers.erreur(400, "requête malformée")

    @app.exception_handler(HTTPException)
    async def _http(request, exc):
        """`{"error": ...}`, la forme que la page lit -- jamais `{"detail": ...}`."""
        detail = exc.detail
        if exc.status_code == 404 and detail == "Not Found":
            detail = "inconnu"
        return headers.erreur(exc.status_code, detail)

    # Le préflight est traité par le middleware, AVANT le routeur -- voir
    # `headers.EnTetes`. Il n'y a donc pas de route `OPTIONS` ici, et il ne faut
    # pas en ajouter une : une route attrape-tout ferait répondre 405 au lieu de
    # 404 sur tout chemin inconnu.

    app.include_router(sante.router)
    app.include_router(catalogue.router)
    app.include_router(soumission.router)
    app.include_router(compte.router)
    app.include_router(progression.router)
    app.include_router(forum.router)
    # EN DERNIER, ET SEULEMENT S'IL Y A UNE PAGE À SERVIR. Ce routeur finit par
    # un attrape-tout `/{nom:path}` : monté plus haut, il masquerait toutes les
    # routes déclarées après lui. Sans `CTESTER_PAGE`, cette origine ne répond
    # plus que sur des données -- l'état visé par la séparation front/back.
    if config.PAGE:
        app.include_router(page.router)
    return app


app = create_app()


def _avertir():
    """Ce qu'un déploiement à moitié configuré doit dire dans `docker logs`.

    UNE FONCTIONNALITÉ FACULTATIVE MAL CONFIGURÉE NE DOIT PAS EMPORTER LE JUGE.
    Refuser de démarrer sur une faute de frappe dans une variable OIDC
    empêcherait tout le monde de tester du code, pour une fonctionnalité que
    personne n'a encore utilisée ce jour-là. Elle se tait donc, mais bruyamment.
    """
    if config.OIDC_ISSUER and not security.oidc_enabled():
        print("connexion desactivee : il faut CTESTER_OIDC_ISSUER en https,"
              " CTESTER_OIDC_CLIENT_ID et CTESTER_DB_DSN", file=sys.stderr)
    # « Personne ne clique dessus » et « il n'existe pas » se ressemblent trop
    # de l'extérieur pour qu'on laisse deviner lequel des deux.
    if security.oidc_enabled() and not config.FORUM_MODERATORS:
        print("discussions desactivees : CTESTER_FORUM_MODERATORS est vide"
              " (liste de `sub` OIDC separes par des virgules)", file=sys.stderr)
    if config.DOCS:
        print("ATTENTION : CTESTER_DOCS=1, /docs et /openapi.json sont publics",
              file=sys.stderr)


if __name__ == "__main__":
    import uvicorn

    if not config.KEY:
        raise SystemExit("CTESTER_KEY est vide : le service refuse de démarrer")
    _avertir()
    os.makedirs(config.SPOOL, exist_ok=True)

    uvicorn.run(
        app,
        host="0.0.0.0",  # noqa: S104 -- le conteneur n'expose rien sur l'hôte
        port=config.PORT,
        # UN SEUL WORKER : voir le docstring de ce module.
        workers=1,
        # `server_header` retire `Server: uvicorn` ; la date reste, les caches en
        # ont besoin. Annoncer sa version de serveur ne sert que celui qui
        # cherche une version vulnérable.
        server_header=False,
        # Les en-têtes de proxy ne sont lus que derrière NPM. `client_id()` s'en
        # sert pour compter les quotas -- et il préfère de toute façon
        # `CF-Connecting-IP`, que Cloudflare écrase toujours.
        proxy_headers=True,
        # Silence sur le chemin heureux : le sondage de `/r/<id>` produit des
        # centaines de 200 par TP, qui noieraient tout ce qui est intéressant
        # dans `docker logs`. Les erreurs, elles, passent toujours.
        access_log=False,
    )
