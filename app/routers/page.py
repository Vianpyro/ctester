"""The page, served by this process. TEMPORARY.

This router is only mounted if `config.PAGE` is set, and it will disappear
once GitHub Pages serves the page for good. It stays for two reasons, and no
more:

  * `python3 app/main.py` then serves the page AND the API on the same
    origin, so `web/config.js` falls back to its `""` default and "launch and
    test" mode keeps working with nothing deployed;
  * it sets the CSP as a HEADER, which GitHub Pages cannot do -- this is the
    only place `frame-ancestors` truly exists.

EXPLICIT ALLOW-LIST, NOT `StaticFiles`. This process must never be able to
serve an arbitrary file from its filesystem, however creative the requested
path. `StaticFiles` mounts a DIRECTORY; here, every served name is spelled out
below.
"""

import config
import headers
from fastapi import APIRouter, Request

router = APIRouter(include_in_schema=False)

# File name -> its type. A CLOSED list: `.js` does not open the directory,
# and `/vendor/` is not an open directory either -- both libraries there are
# named with their version.
SERVIS = dict(
    {"index.html": "text/html; charset=utf-8",
     "style.css": "text/css; charset=utf-8",
     "favicon.svg": "image/svg+xml"},
    **{nom: "text/javascript; charset=utf-8"
       for nom in ("config.js", "app.js", "quiz.js", "compte.js",
                   "progres.js", "forum.js", "exporter.js",
                   # A module absent from this list falls to a 404 and the
                   # button goes inert with a message -- which is exactly what
                   # happened the first time `exporter.js` was added.
                   "leaderboard.js", "collection.js",
                   # The team workspace. Downloaded only when a signed-in
                   # student opens an exercise that belongs to a team
                   # assignment -- so never on the anonymous path, and never
                   # for the ten labs that are not one.
                   "team.js")},
    **{nom: "text/javascript; charset=utf-8" for nom in config.VENDOR},
)


@router.api_route("/", methods=["GET", "HEAD"])
def racine(request: Request):
    """The document. `HEAD` goes through the SAME code as `GET`, with no body.

    A `HEAD` that announced a different cache policy or a different CSP
    would be a revalidation trap: the browser would keep a validated response
    against headers it never actually had.
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
