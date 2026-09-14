#!/usr/bin/env python3

import os
import sys

import config
import deps
import headers
import security
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from routers import (account, catalog, forum, health, leaderboard, page,
                     progress, scratch, submission, team)
from starlette.exceptions import HTTPException


def create_app():
    app = FastAPI(
        title="ctester",
        docs_url="/docs" if config.DOCS else None,
        redoc_url="/redoc" if config.DOCS else None,
        openapi_url="/openapi.json" if config.DOCS else None,
        default_response_class=headers.JSON,
    )
    app.add_middleware(headers.HeaderMiddleware)

    @app.exception_handler(deps.Refusal)
    async def _refusal(request, exc):
        return headers.error(exc.code, exc.message, **exc.extra)

    # FastAPI's default 422 body echoes the rejected input, which may hold code or a token.
    @app.exception_handler(RequestValidationError)
    async def _validation(request, exc):
        return headers.error(400, "requête malformée")

    @app.exception_handler(HTTPException)
    async def _http(request, exc):
        detail = exc.detail
        if exc.status_code == 404 and detail == "Not Found":
            detail = "inconnu"
        return headers.error(exc.status_code, detail)

    app.include_router(health.router)
    app.include_router(catalog.router)
    app.include_router(submission.router)
    app.include_router(account.router)
    app.include_router(progress.router)
    app.include_router(leaderboard.router)
    app.include_router(forum.router)
    app.include_router(team.router)
    app.include_router(scratch.router)
    # Last: the page router ends with a catch-all route.
    if config.PAGE:
        app.include_router(page.router)
    return app


app = create_app()


def _warn():
    if config.OIDC_ISSUER and not security.oidc_enabled():
        print("sign-in disabled: needs an https CTESTER_OIDC_ISSUER,"
              " CTESTER_OIDC_CLIENT_ID and CTESTER_DB_DSN", file=sys.stderr)
    if security.oidc_enabled() and not config.FORUM_MODERATORS:
        print("forum disabled: CTESTER_FORUM_MODERATORS is empty"
              " (comma-separated OIDC subjects)", file=sys.stderr)
    if config.DOCS:
        print("WARNING: CTESTER_DOCS=1, /docs and /openapi.json are public",
              file=sys.stderr)
    from uvicorn.protocols.websockets.auto import AutoWebSocketsProtocol
    if AutoWebSocketsProtocol is None:
        print("WARNING: no WebSocket implementation installed, /team/live and"
              " /scratch/live will answer 501. Install wsproto (requirements.txt)",
              file=sys.stderr)


if __name__ == "__main__":
    import uvicorn

    if not config.KEY:
        raise SystemExit("CTESTER_KEY is empty, refusing to start")
    _warn()
    os.makedirs(config.SPOOL, exist_ok=True)

    uvicorn.run(
        app,
        host="0.0.0.0",  # noqa: S104 -- the container exposes nothing on the host
        port=config.PORT,
        # Quotas, presence, the token cache and collaboration rooms are per process.
        workers=1,
        server_header=False,
        proxy_headers=True,
        access_log=False,
    )
