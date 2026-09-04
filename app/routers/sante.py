"""Santé, présence, et ce que ce déploiement offre.

Les trois routes que la page interroge avant de savoir quoi dessiner. Aucune ne
demande de jeton -- `/oidc.json` doit répondre à un anonyme, sinon la page ne
saurait jamais qu'un bouton de connexion existe.
"""

import time

import config
import deps
import security
from fastapi import APIRouter, Query, Request
from services import forum as forum_service

router = APIRouter(tags=["sante"])


@router.get("/healthz")
def healthz() -> dict[str, bool]:
    """Ce que le `healthcheck` du conteneur interroge toutes les 30 s.

    IL NE TOUCHE NI LA BASE NI LE SPOOL, et c'est voulu : il répond « ce
    processus sert du HTTP », pas « toute la chaîne va bien ». Un `/healthz` qui
    interrogerait Postgres ferait redémarrer en boucle le conteneur web à la
    première panne de la base -- alors que le parcours anonyme, lui, fonctionne
    encore parfaitement.
    """
    return {"ok": True}


@router.get("/live")
def live(request: Request, id: str = Query("")):
    """Combien de fenêtres sont ouvertes, à la minute près.

    LA SEULE ENTORSE À « L'ANONYME N'ÉMET AUCUNE REQUÊTE », et elle est assumée :
    le battement va vers un `dict` en mémoire, jamais vers la base ni vers un
    compte, et ne porte aucun jeton.

    `id` VIENT DU NAVIGATEUR (tiré au hasard, gardé le temps de l'onglet), donc
    falsifiable et non authentifié : c'est un chiffre affiché, pas un contrôle.
    Sans lui on retombe sur l'IP -- une école compte alors pour une fenêtre,
    ce qui est faux mais n'expose rien.

    TRONQUÉ À 64, PAS REFUSÉ AU-DELÀ. Un `max_length` sur le paramètre ferait
    répondre 400 à un jeton trop long : ce serait la seule route anonyme capable
    d'échouer, pour un compteur d'affichage. `battement()` avale l'erreur et le
    compteur reste caché -- mais une panne silencieuse reste une panne.
    """
    qui = (id or security.client_id(request.headers, deps.pair_tcp(request)))[:64]
    with deps.verrou:
        n = deps.presence.touch(qui, time.time())
    return {"n": n}


@router.get("/oidc.json")
def oidc():
    """Ce que ce déploiement offre. Un objet vide veut dire « rien de plus ».

    La page l'interroge avant d'afficher quoi que ce soit : sans `issuer`, tout
    le bloc de connexion reste inerte et le parcours anonyme est exactement ce
    qu'il était. `forum` voyage ici parce que c'est déjà l'endpoint « ce qui est
    offert » -- faux ou absent, le bouton n'existe pas et `forum.js` n'est
    jamais demandé.
    """
    if not security.oidc_enabled():
        return {}
    return {"issuer": config.OIDC_ISSUER, "client_id": config.OIDC_CLIENT_ID,
            "forum": forum_service.forum_enabled()}
