"""La page, servie par ce processus. TEMPORAIRE.

Ce routeur n'est monté que si `config.PAGE` est défini, et il disparaîtra quand
GitHub Pages servira la page pour de bon (voir `docs/split-front_back/plan.md`).
Il reste pour deux raisons, et pas une de plus :

  * `python3 app/main.py` sert alors la page ET l'API sur la même origine, donc
    `web/config.js` retombe sur son repli `""` et le mode « je lance et je
    teste » continue de marcher sans déployer quoi que ce soit ;
  * il pose la CSP en EN-TÊTE, ce que GitHub Pages ne sait pas faire -- c'est le
    seul endroit où `frame-ancestors` existe vraiment.

LISTE BLANCHE EXPLICITE, PAS `StaticFiles`. Ce processus ne doit jamais pouvoir
servir un fichier arbitraire de son système de fichiers, quelle que soit la
créativité du chemin demandé. `StaticFiles` monte un RÉPERTOIRE ; ici, chaque
nom servi est écrit en toutes lettres ci-dessous.
"""

import config
import headers
from fastapi import APIRouter, Request

router = APIRouter(include_in_schema=False)

# Le nom de fichier -> son type. Une liste CLOSE : `.js` n'ouvre pas le
# répertoire, et `/vendor/` n'est pas un répertoire ouvert non plus -- les deux
# bibliothèques y sont nommées avec leur version.
SERVIS = dict(
    {"index.html": "text/html; charset=utf-8",
     "style.css": "text/css; charset=utf-8",
     "favicon.svg": "image/svg+xml"},
    **{nom: "text/javascript; charset=utf-8"
       for nom in ("config.js", "app.js", "quiz.js", "compte.js",
                   "progres.js", "forum.js", "exporter.js")},
    **{nom: "text/javascript; charset=utf-8" for nom in config.VENDOR},
)


@router.api_route("/", methods=["GET", "HEAD"])
def racine(request: Request):
    """Le document. `HEAD` passe par le MÊME code que `GET`, sans le corps.

    Un `HEAD` qui annoncerait une autre politique de cache ou une autre CSP
    serait un piège à revalidation : le navigateur garderait une réponse validée
    contre des en-têtes qu'elle n'a jamais eus.
    """
    return _servir(request, "index.html")


@router.api_route("/{nom:path}", methods=["GET", "HEAD"])
def fichier(nom: str, request: Request):
    if nom not in SERVIS:
        return headers.erreur(404, "inconnu")
    return _servir(request, nom)


def _servir(request, nom):
    return headers.fichier_du_disque(request, config.PAGE, nom, SERVIS[nom],
                                     config.OIDC_ISSUER)
