import os
import re

import config
import headers
from fastapi import APIRouter, Request

router = APIRouter(include_in_schema=False)

JS = "text/javascript; charset=utf-8"

SERVED = {
    "index.html": "text/html; charset=utf-8",
    "favicon.svg": "image/svg+xml",
    "theme.js": JS,
    # Must be served from the root, or its scope cannot cover the page.
    "sw.js": JS,
}

ASSET_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]{0,127}\.(js|css|map|svg|woff2)\Z")

ASSET_TYPES = {
    "js": JS,
    "css": "text/css; charset=utf-8",
    "map": "application/json; charset=utf-8",
    "svg": "image/svg+xml",
    "woff2": "font/woff2",
}


@router.api_route("/", methods=["GET", "HEAD"])
def index(request: Request):
    return _serve(request, "index.html", SERVED["index.html"])


@router.api_route("/assets/{name}", methods=["GET", "HEAD"])
def asset(name: str, request: Request):
    if not ASSET_RE.match(name):
        return headers.error(404, "inconnu")
    path = os.path.join(config.PAGE, "assets", name)
    if not os.path.isfile(path):
        return headers.error(404, "inconnu")
    # The build puts the content hash in the name, so these bytes never change under it.
    return _serve(request, os.path.join("assets", name),
                  ASSET_TYPES[name.rsplit(".", 1)[1]], cache=headers.IMMUTABLE)


@router.api_route("/{name:path}", methods=["GET", "HEAD"])
def static_file(name: str, request: Request):
    if name not in SERVED:
        return headers.error(404, "inconnu")
    return _serve(request, name, SERVED[name])


def _serve(request, name, mime_type, cache="no-cache"):
    return headers.file_from_disk(request, config.PAGE, name, mime_type,
                                  config.OIDC_ISSUER, cache=cache)
