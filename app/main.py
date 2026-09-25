#!/usr/bin/env python3

import os

import config
import deps
import headers
import log
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
        return headers.error(400, "malformed_request")

    @app.exception_handler(HTTPException)
    async def _http(request, exc):
        detail = exc.detail
        if exc.status_code == 404 and detail == "Not Found":
            detail = "unknown"
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
        log.event("config.sign_in_disabled", log.WARN,
                  "sign-in disabled: needs an https CTESTER_OIDC_ISSUER,"
                  " CTESTER_OIDC_CLIENT_ID and CTESTER_DB_DSN")
    if security.oidc_enabled() and not config.FORUM_MODERATORS:
        log.event("config.forum_disabled", log.WARN,
                  "forum disabled: CTESTER_FORUM_MODERATORS is empty"
                  " (comma-separated OIDC subjects)")
    if config.DOCS:
        log.event("config.docs_public", log.WARN,
                  "CTESTER_DOCS=1, /docs and /openapi.json are public")
    from uvicorn.protocols.websockets.auto import AutoWebSocketsProtocol
    if AutoWebSocketsProtocol is None:
        log.event("config.no_websocket", log.WARN,
                  "no WebSocket implementation installed, /team/live and /scratch/live"
                  " will answer 501. Install wsproto (requirements.txt)")


def _started():
    log.event("service.start", log.INFO, "listening on port %d" % config.PORT, {
        "ctester.feature.sign_in": security.oidc_enabled(),
        "ctester.feature.forum": deps.forum_service.forum_enabled(),
        "ctester.feature.scratch": config.SCRATCH,
        "ctester.feature.discord": bool(config.DISCORD_WEBHOOK),
    })


if __name__ == "__main__":
    import uvicorn

    log.setup("ctester-web")
    if not config.KEY:
        log.event("config.no_key", log.FATAL, "CTESTER_KEY is empty, refusing to start")
        raise SystemExit(1)
    _warn()
    _started()
    os.makedirs(config.SPOOL, exist_ok=True)

    uvicorn.run(
        app,
        host="0.0.0.0",  # noqa: S104 -- the container exposes nothing on the host
        port=config.PORT,
        # Quotas, presence, the token cache and collaboration rooms are per process.
        workers=1,
        server_header=False,
        proxy_headers=True,
        # Requests are logged by headers.HeaderMiddleware, which names the route, not the path.
        access_log=False,
        log_config=None,
    )
