"""The page, served by this process. TEMPORARY.

This router is only mounted if `config.PAGE` is set, and it will disappear once
GitHub Pages serves the page for good. It stays for two reasons, and no more:

  * `python3 app/main.py` then serves the page AND the API on the same origin,
    so `frontend/src/lib/config.ts` falls back to its `""` default and "launch
    and test" mode keeps working with nothing deployed;
  * it sets the CSP as a HEADER, which GitHub Pages cannot do -- this is the
    only place `frame-ancestors` truly exists.

WHAT IT SERVES IS THE BUILT BUNDLE (`frontend/dist`), not the sources: `npm run
build` first, and then `CTESTER_PAGE=frontend/dist python3 app/main.py`. The
sources are TypeScript and Svelte; nothing in this container compiles anything.

TWO CLOSED RULES, NOT `StaticFiles`. This process must never be able to serve an
arbitrary file from its filesystem, however creative the requested path:

  * the ROOT files are spelled out one by one, exactly as before;
  * `assets/<name>` is accepted only when `<name>` matches a closed pattern
    with NO path separator and no dot-dot in it, AND that exact file exists in
    the build's own `assets/` directory.

The second rule is what the build step costs, and it is worth stating why it is
not a directory mount: the bundle's file names carry a CONTENT HASH
(`index-CODmhrno.js`), which is what replaced the hand-maintained `?v=` token the
page used to carry -- a token that had to be edited in two files and went stale
silently. A name cannot be enumerated in advance, so the rule matches its SHAPE
and then requires the file to be one the build actually wrote. `..`, a slash and
a backslash are all outside the pattern, so there is nothing to traverse.
"""

import os
import re

import config
import headers
from fastapi import APIRouter, Request

router = APIRouter(include_in_schema=False)

JS = "text/javascript; charset=utf-8"

# The root of the build. One line each, and the list is closed.
SERVIS = {
    "index.html": "text/html; charset=utf-8",
    "favicon.svg": "image/svg+xml",
    # THE PRE-PAINT THEME SCRIPT. A classic script with a STABLE name, on
    # purpose: it is referenced from `index.html` by that name, and it is the
    # only script in the document that is not part of the bundle.
    "theme.js": JS,
}

# What the build writes under `assets/`. A letter, a digit, `-`, `_` and `.`,
# and nothing else: no separator, so no path to walk out of.
ASSET_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]{0,127}\.(js|css|map|svg|woff2)\Z")

ASSET_TYPES = {
    "js": JS,
    "css": "text/css; charset=utf-8",
    # Source maps ship: the page is our own code, and whoever debugs a
    # production report benefits.
    "map": "application/json; charset=utf-8",
    "svg": "image/svg+xml",
    "woff2": "font/woff2",
}


@router.api_route("/", methods=["GET", "HEAD"])
def racine(request: Request):
    """The document. `HEAD` goes through the SAME code as `GET`, with no body.

    A `HEAD` that announced a different cache policy or a different CSP would
    be a revalidation trap: the browser would keep a validated response against
    headers it never actually had.
    """
    return _servir(request, "index.html", SERVIS["index.html"])


@router.api_route("/assets/{nom}", methods=["GET", "HEAD"])
def actif(nom: str, request: Request):
    """One file of the build. See this module's docstring for why the rule is a
    pattern plus an existence check rather than an enumeration."""
    if not ASSET_RE.match(nom):
        return headers.erreur(404, "inconnu")
    chemin = os.path.join(config.PAGE, "assets", nom)
    if not os.path.isfile(chemin):
        return headers.erreur(404, "inconnu")
    return _servir(request, os.path.join("assets", nom),
                   ASSET_TYPES[nom.rsplit(".", 1)[1]])


@router.api_route("/{nom:path}", methods=["GET", "HEAD"])
def fichier(nom: str, request: Request):
    if nom not in SERVIS:
        return headers.erreur(404, "inconnu")
    return _servir(request, nom, SERVIS[nom])


def _servir(request, nom, type_mime):
    return headers.fichier_du_disque(request, config.PAGE, nom, type_mime,
                                     config.OIDC_ISSUER)
