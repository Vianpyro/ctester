"""Santé du service.

`/healthz` est ce que le `healthcheck` du conteneur interroge toutes les 30 s.
Il ne touche NI la base NI le spool, et c'est voulu : il répond « ce processus
sert du HTTP », pas « toute la chaîne va bien ». Un `/healthz` qui interrogerait
Postgres ferait redémarrer en boucle le conteneur web à la première panne de la
base -- alors que le parcours anonyme, lui, fonctionne encore parfaitement.
"""

from fastapi import APIRouter

router = APIRouter(tags=["sante"])


@router.get("/healthz")
def healthz() -> dict[str, bool]:
    return {"ok": True}
