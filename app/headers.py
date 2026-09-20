import functools
import gzip
import hashlib
import os

import config
import csp
from starlette.datastructures import MutableHeaders
from starlette.responses import JSONResponse, Response

PREFLIGHT = {
    "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
    "Access-Control-Allow-Headers": "Authorization, Content-Type",
    "Access-Control-Max-Age": "86400",
}


class HeaderMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        origin = ""
        for name, value in scope["headers"]:
            if name == b"origin":
                origin = value.decode("latin-1").strip().rstrip("/")
                break
        known = bool(origin) and origin in config.ORIGINS

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                response_headers = MutableHeaders(scope=message)
                if known:
                    response_headers["Access-Control-Allow-Origin"] = origin
                # A single Vary header: some caches drop one of two separate ones.
                response_headers["Vary"] = "Accept-Encoding, Origin"
                if "cache-control" not in response_headers:
                    response_headers["Cache-Control"] = "no-store"
            await send(message)

        if scope["method"] in ("POST", "PUT"):
            too_large = _body_out_of_bounds(scope)
            if too_large:
                await _respond(send_with_headers, 413,
                               b'{"error": "corps trop gros ou vide"}')
                return

        # Preflight lives here: an OPTIONS catch-all route turns unknown paths into 405s.
        if scope["method"] == "OPTIONS":
            await _respond(send_with_headers, 204, b"", PREFLIGHT)
            return

        await self.app(scope, receive, send_with_headers)


def _body_out_of_bounds(scope):
    """Checked before parsing. No Content-Length is refused too, so POST/PUT always send a body."""
    raw = b""
    for name, value in scope["headers"]:
        if name == b"content-length":
            raw = value
            break
    try:
        length = int(raw)
    except ValueError:
        return True
    return not 0 < length <= config.MAX_CODE + 4096


async def _respond(send_with_headers, code, body, response_headers=None):
    raw_headers = [(b"content-length", str(len(body)).encode())]
    if body:
        raw_headers.append((b"content-type", b"application/json; charset=utf-8"))
    raw_headers += [(k.lower().encode(), v.encode())
                    for k, v in (response_headers or {}).items()]
    await send_with_headers({"type": "http.response.start", "status": code,
                             "headers": raw_headers})
    await send_with_headers({"type": "http.response.body", "body": body})


class JSON(JSONResponse):
    media_type = "application/json; charset=utf-8"


def error(code, message, key="error", **extra):
    return JSON(dict({key: message}, **extra), status_code=code)


# A hashed asset name changes whenever its bytes change, so the answer never goes stale.
IMMUTABLE = "public, max-age=31536000, immutable"

# Above this, a file is read and compressed per request rather than held: a rendered
# statement page is large and rarely asked for twice in a row.
CACHE_MAX_BYTES = 256 * 1024


def _pack(body):
    return gzip.compress(body, 6) if len(body) >= 1024 else None


@functools.lru_cache(maxsize=48)
def _prepared(path, stamp):
    """Read, hashed and compressed once per file and per release. The web container has a
    quarter of a CPU and every student of the class asks for exactly the same bytes."""
    with open(path, "rb") as fh:
        body = fh.read()
    return body, _pack(body), hashlib.sha256(body).hexdigest()[:16]


def _sendable(request, body, packed, digest, ctype, issuer, cache):
    compressed = packed is not None and "gzip" in request.headers.get("accept-encoding", "")
    # One ETag per representation, or a cache could validate gzip against identity.
    etag = '"' + digest + ("-gz" if compressed else "") + '"'

    response_headers = {"ETag": etag, "Cache-Control": cache}
    if ctype.startswith("text/html"):
        response_headers["Content-Security-Policy"] = csp.csp(body, issuer)

    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=response_headers)
    if compressed:
        response_headers["Content-Encoding"] = "gzip"
        return Response(packed, media_type=ctype, headers=response_headers)
    return Response(body, media_type=ctype, headers=response_headers)


def file_response(request, body, ctype, issuer="", cache="no-cache"):
    return _sendable(request, body, _pack(body), hashlib.sha256(body).hexdigest()[:16],
                     ctype, issuer, cache)


def file_from_disk(request, base, name, ctype, issuer="", private=False,
                   cache="no-cache"):
    path = os.path.join(base, name)
    try:
        stamp = os.stat(path)
        if stamp.st_size > CACHE_MAX_BYTES:
            with open(path, "rb") as fh:
                body = fh.read()
            packed, digest = _pack(body), hashlib.sha256(body).hexdigest()[:16]
        else:
            body, packed, digest = _prepared(path, (stamp.st_mtime_ns, stamp.st_size))
    except OSError:
        return error(500, "fichier manquant")
    if private:
        # No ETag and no no-cache: the middleware's no-store keeps staff-only files
        # out of shared caches, where a student's request could revalidate them.
        if packed is not None and "gzip" in request.headers.get("accept-encoding", ""):
            return Response(packed, media_type=ctype, headers={"Content-Encoding": "gzip"})
        return Response(body, media_type=ctype)
    return _sendable(request, body, packed, digest, ctype, issuer, cache)
