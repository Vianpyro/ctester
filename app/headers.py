"""ctester -- output headers: CORS, `Vary`, cache, CSP, ETag.

EVERYTHING THAT MUST APPEAR ON *EVERY* RESPONSE LIVES HERE, in a single
middleware. Responses come from everywhere -- a route, an exception handler, a
304, a Starlette 404 nobody wrote -- and a response with no CORS header is an
invisible server-side outage: only the student's browser ever sees it.

NOT Starlette's `CORSMiddleware`, and that is deliberate:
  * it answers 400 to a preflight from an unknown origin, where we want to set
    nothing at all and let the browser block -- a forgotten setting must not
    look like a service outage;
  * it adds a SECOND `Vary` line instead of merging. Two separate `Vary` lines
    are legal but poorly recombined by some caches, and a cache that drops
    `Origin` serves one origin's response to another.
"""

import gzip
import hashlib
import os

import csp
from starlette.datastructures import MutableHeaders
from starlette.responses import JSONResponse, Response

import config

# The preflight, for every route. `Max-Age` at 86400 is what keeps the
# front/back split from costing one extra round trip per request: without it,
# every PUT and every DELETE would pay for one.
#
# DELETE IS IN THE LIST AND MUST STAY THERE -- the page deletes an account
# (`DELETE /moi`) and a forum message. Forgetting it only breaks cross-origin,
# meaning only production, and only these two buttons.
PREFLIGHT = {
    "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
    "Access-Control-Allow-Headers": "Authorization, Content-Type",
    "Access-Control-Max-Age": "86400",
}


class HeaderMiddleware:
    """ASGI middleware: CORS, `Vary`, and `no-store` by default.

    PURE ASGI AND NOT `BaseHTTPMiddleware`: that one buffers the response in
    memory and wraps exceptions, which changes the exit code of routes that
    depend on it. Here we only rewrite the outgoing header.

    `no-store` IS THE DEFAULT, and the exception is explicit. No data
    response -- verdict, progression, forum, preferences -- must be kept; only
    files set `no-cache` themselves (see `fichier()`), and they are the only
    ones. A default the other way would mean an account route added one
    evening during a session gets cached with nobody asking for that.
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
                # NO `Access-Control-Allow-Credentials`: there is no cookie
                # here, the token travels in the `Authorization` header.
                #
                # A SINGLE `Vary` HEADER, and it announces both axes. The
                # assignment replaces whatever was already there -- that is
                # the point: two lines must never coexist. `Accept-Encoding`
                # stays there even on uncompressed responses: the constant is
                # simply everywhere, a computed value would be one more `if`
                # on every response.
                entetes["Vary"] = "Accept-Encoding, Origin"
                if "cache-control" not in entetes:
                    entetes["Cache-Control"] = "no-store"
            await send(message)

        # THE BODY BOUND LIVES HERE, BEFORE ANY PARSING, and for every route.
        # Uvicorn HAS NO body size limit: without this check, a POST
        # announcing 2 GB would get read in full before the slightest
        # validation runs. Setting it once here, rather than at the top of
        # every router, is what guarantees a route added one evening during a
        # session is born bounded.
        if scope["method"] in ("POST", "PUT"):
            trop = _corps_hors_bornes(scope)
            if trop:
                await _repondre(envoyer, 413,
                                b'{"error": "corps trop gros ou vide"}')
                return

        # THE PREFLIGHT DOES NOT GO THROUGH THE ROUTER, and that is what
        # makes it correct. A catch-all `OPTIONS /{chemin:path}` route would
        # answer 405 to any UNKNOWN path: Starlette keeps that route's
        # partial match (right path, wrong method) and never falls through to
        # its 404. A `/whatever` would then start answering "method not
        # allowed", which is false and which confirms in passing that it
        # exists.
        if scope["method"] == "OPTIONS":
            await _repondre(envoyer, 204, b"", PREFLIGHT)
            return

        await self.app(scope, receive, envoyer)


def _corps_hors_bornes(scope):
    """True if `Content-Length` is missing, unreadable, or out of bounds.

    Absent counts as "out of bounds": a `chunked` request does not announce
    its size, and we do not read a body whose length we do not know.
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
    """A complete response straight from the middleware, bypassing the router."""
    lignes = [(b"content-length", str(len(corps)).encode())]
    if corps:
        lignes.append((b"content-type", b"application/json; charset=utf-8"))
    lignes += [(k.lower().encode(), v.encode())
               for k, v in (entetes or {}).items()]
    await envoyer({"type": "http.response.start", "status": code,
                   "headers": lignes})
    await envoyer({"type": "http.response.body", "body": corps})


class JSON(JSONResponse):
    """`application/json; charset=utf-8`, explicitly.

    Starlette renders plain `application/json` -- correct under RFC 8259
    (JSON is always UTF-8), but not what this service has always advertised.
    The explicit `charset` costs fifteen bytes per response and avoids
    wondering, the day something breaks, whether an intermediary (Cloudflare,
    a cache, a school proxy) treats the two the same.

    Set as `default_response_class`: every route that returns a `dict` goes
    through here, with none of them having to think about it.
    """

    media_type = "application/json; charset=utf-8"


def erreur(code, message, cle="error", **extra):
    """The error body the page expects: `{"error": "..."}`, and nothing else.

    A SINGLE SHAPE, because the page reads `error` off the body and displays
    whatever it finds there. `cle` exists only for the verdict poll, which answers
    `{"state": ...}`; `extra` carries `retry_after` on a 429, which the page
    uses to say how long to wait instead of inviting a re-click.
    """
    return JSON(dict({cle: message}, **extra), status_code=code)


def fichier(request, body, ctype, issuer=""):
    """A static file, revalidated on every visit, transferred if needed.

    `no-cache` DOES NOT MEAN "do not cache": it means "keep it, but ask me
    again before serving it". The browser therefore always checks back, and a
    deployed fix is always seen right away -- that is what `no-store`
    protected, and it is intact. What changes is that an unchanged file comes
    back as an empty 304 instead of the whole thing: the page, its stylesheet
    and its script total 65 KB, and a student reloads a lot.

    `no-store` ALSO forbade the browser's back/forward cache (bfcache): with
    it, the Back button redid the whole page.
    """
    etiquette = '"' + hashlib.sha256(body).hexdigest()[:16]
    # THE CSP IS COMPUTED ON THE PLAIN BODY, before compression: the policy is
    # about the document, not its transport.
    politique = csp.csp(body, issuer) if ctype.startswith("text/html") else ""
    # ONE ETAG PER REPRESENTATION. Two different bodies for the same URL --
    # the original and the gzip -- must not share an ETag: an intermediate
    # cache would serve one while believing it validated the other.
    comprime = (len(body) >= 1024
                and "gzip" in request.headers.get("accept-encoding", ""))
    if comprime:
        body = gzip.compress(body, 6)
        etiquette += "-gz"
    etiquette += '"'

    entetes = {"ETag": etiquette, "Cache-Control": "no-cache"}
    # ON THE 304 TOO. The browser replays the kept response, refreshed with
    # these headers; a CSP that only appeared on the 200 would then disappear
    # from the second visit onward, i.e. almost always.
    if politique:
        entetes["Content-Security-Policy"] = politique

    if request.headers.get("if-none-match") == etiquette:
        return Response(status_code=304, headers=entetes)
    if comprime:
        entetes["Content-Encoding"] = "gzip"
    return Response(body, media_type=ctype, headers=entetes)


def fichier_du_disque(request, base, nom, ctype, issuer="", prive=False):
    """A file from disk, and `base` SAYS WHICH OF THE TWO DIRECTORIES.

    No default, on purpose: the page (`config.PAGE`) and the release the
    worker publishes (`config.PUBLISHED`) have lived apart since the page was
    meant for GitHub Pages, and both go through here. A default would make it
    look for `exercises/<id>.json` in the page's directory -- a 500 on every
    statement and every quiz, in production only, because a harness that
    mounts both in the same place cannot see it.

    `nom` NEVER COMES FROM THE URL AS-IS: callers rebuild it from the catalog,
    from a closed list, or -- for the built bundle's content-hashed assets --
    from a closed PATTERN with no path separator in it, checked against a file
    the build actually wrote. There is therefore no path to traverse, and no
    `..` to filter: filtering would mean accepting an input, which we do not.

    `prive=True` MEANS "NOT A FILE", AND IT IS A SECURITY LINE. `fichier()`
    sets `no-cache` + ETag, which tells Cloudflare and the browser to KEEP the
    body and revalidate it -- correct for the page and the open catalog, wrong
    for a body only a moderator may see: a student's request could revalidate
    into a kept staff statement. Returning a bare `Response` lets the
    middleware's default `no-store` stand, which is the complete answer -- no
    `Vary: Authorization` to remember, and nothing stored anywhere to leak.
    """
    try:
        with open(os.path.join(base, nom), "rb") as fh:
            corps = fh.read()
    except OSError:
        return erreur(500, "fichier manquant")
    if prive:
        return Response(corps, media_type=ctype)
    return fichier(request, corps, ctype, issuer)
