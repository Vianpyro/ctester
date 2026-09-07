#!/usr/bin/env python3
"""ctester -- the C judge's API. File managed by Ansible: edit the role.

This process compiles NOTHING and executes NOTHING. It validates a submission,
writes it into the spool, and reads the verdict a host worker drops there. It
has neither the Docker socket nor access to the test directory -- that is the
whole reason it can be exposed to the Internet.

ONE WORKER, ALWAYS, and this is not a performance setting. Quotas, the
presence counter, the OIDC token cache and `state.py`'s single connection are
PROCESS-MEMORY state. Two workers means two counters: every quota silently
doubles, and the queue cap lets through twice what it advertises. That is why
the launch lives here, in `__main__`, and not in a Compose command line that
someone will one day copy with `--workers 4`. The day a second process is
truly needed, Redis or Postgres holds these counters, not uvicorn.

THE ENDPOINTS ARE `def`, NOT `async def`, and that is deliberate. Starlette
then runs each one in its threadpool, which keeps `state.py` synchronous: its
data-modifying CTEs, its `INSERT ... SELECT` whose `WHERE` clause IS the
access control, and its column GRANTs are exercised against a real Postgres by
`test_postgres.py`. Rewriting them in async SQLAlchemy would swap proven SQL
for SQL yet to be proven, in the one layer where a mistake grants access to
someone else's data.
"""

import os
import sys

import config
import deps
import headers
import security
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from routers import (account, catalog, forum, health, leaderboard, page,
                     progress, submission, team)
from starlette.exceptions import HTTPException


def create_app():
    app = FastAPI(
        title="ctester",
        # AUTOMATIC DOCUMENTATION IS OFF UNLESS EXPLICITLY REQUESTED. `None`
        # removes the route, it does not protect it: there is therefore
        # nothing to bypass. See `config.DOCS`.
        docs_url="/docs" if config.DOCS else None,
        redoc_url="/redoc" if config.DOCS else None,
        openapi_url="/openapi.json" if config.DOCS else None,
        # The `charset=utf-8` this service has always advertised -- see
        # `headers.JSON`.
        default_response_class=headers.JSON,
    )
    app.add_middleware(headers.HeaderMiddleware)

    @app.exception_handler(deps.Refus)
    async def _refus(request, exc):
        """Our own refusals: 401, 403, 429, 503, with their `retry_after`."""
        return headers.erreur(exc.code, exc.message, **exc.extra)

    @app.exception_handler(RequestValidationError)
    async def _validation(request, exc):
        """Pydantic's 422 -> 400 `{"error": ...}`, WITHOUT ECHOING THE INPUT.

        FastAPI's default responds 422 with a body that contains the rejected
        value. Two problems: the page reads `out.error` and would not
        understand any of it, and echoing the input back to the sender is a
        free leak -- a rejected body can contain someone's code, or a
        mis-pasted token. The message is therefore constant, and the detail
        stays in the log.
        """
        return headers.erreur(400, "requête malformée")

    @app.exception_handler(HTTPException)
    async def _http(request, exc):
        """`{"error": ...}`, the shape the page reads -- never `{"detail": ...}`."""
        detail = exc.detail
        if exc.status_code == 404 and detail == "Not Found":
            detail = "inconnu"
        return headers.erreur(exc.status_code, detail)

    # The preflight is handled by the middleware, BEFORE the router -- see
    # `headers.HeaderMiddleware`. There is therefore no `OPTIONS` route here, and none
    # should be added: a catch-all route would answer 405 instead of 404 on
    # any unknown path.

    app.include_router(health.router)
    app.include_router(catalog.router)
    app.include_router(submission.router)
    app.include_router(account.router)
    app.include_router(progress.router)
    app.include_router(leaderboard.router)
    app.include_router(forum.router)
    app.include_router(team.router)
    # LAST, AND ONLY IF THERE IS A PAGE TO SERVE. This router ends with a
    # catch-all `/{nom:path}`: mounted earlier, it would shadow every route
    # declared after it. Without `CTESTER_PAGE`, this origin answers only on
    # data -- the state the frontend/backend split is aiming for.
    if config.PAGE:
        app.include_router(page.router)
    return app


app = create_app()


def _avertir():
    """What a half-configured deployment must say in `docker logs`.

    AN OPTIONAL FEATURE, MISCONFIGURED, MUST NOT TAKE THE JUDGE DOWN WITH IT.
    Refusing to start on a typo in an OIDC variable would stop everyone from
    testing code, for a feature nobody has used yet that day. So it stays
    quiet -- but loudly.
    """
    if config.OIDC_ISSUER and not security.oidc_enabled():
        print("connexion desactivee : il faut CTESTER_OIDC_ISSUER en https,"
              " CTESTER_OIDC_CLIENT_ID et CTESTER_DB_DSN", file=sys.stderr)
    # "Nobody clicks it" and "it doesn't exist" look too alike from the
    # outside to leave anyone guessing which one it is.
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
        host="0.0.0.0",  # noqa: S104 -- the container exposes nothing on the host
        port=config.PORT,
        # ONE WORKER ONLY: see this module's docstring.
        workers=1,
        # `server_header` removes `Server: uvicorn`; the date stays, caches
        # need it. Advertising a server version only helps someone looking
        # for a vulnerable one.
        server_header=False,
        # Proxy headers are only read behind NPM. `client_id()` uses them to
        # count quotas -- and prefers `CF-Connecting-IP` anyway, which
        # Cloudflare always overwrites.
        proxy_headers=True,
        # Silence on the happy path: polling `/r/<id>` produces hundreds of
        # 200s per exercise, which would drown out anything interesting in
        # `docker logs`. Errors, though, always come through.
        access_log=False,
    )
