#!/usr/bin/env python3

"""The teacher's dashboard: a separate app on the LAN.

Two boundaries, not one. The proxy host should carry an access list restricted to the
LAN -- a hostname that only resolves on the LAN is a routing convenience, not a
boundary, because the proxy routes on the Host header. On top of that, every /api route
demands a moderator's OIDC token, because the page can show student identities and code.

Nothing here writes to the service: the only table it fills is its own copy of the
judge's run journal.
"""

import os
import sys
from typing import Annotated

import code as code_service
import config
import drain
import overview
import security
import state
from fastapi import Depends, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
PORT = int(os.environ.get("CTESTER_ADMIN_PORT", "8001"))


def moderator(request: Request) -> str:
    """The same test as the student API: the account comes from the validated token,
    never from the request."""
    if not security.oidc_enabled():
        raise _Refus(503, "la connexion n'est pas configurée sur ce déploiement")
    if not security.userinfo_url():
        raise _Refus(503, "l'API n'atteint pas l'IdP : vérifie que le conteneur"
                          " résout CTESTER_OIDC_ISSUER (extra_hosts)")
    sub = security.current_user(request.headers)
    if sub is None:
        raise _Refus(401, "connexion requise ou expirée")
    if not security.is_moderator(sub):
        raise _Refus(403, "réservé à l'enseignant")
    return sub


def _origine(url):
    """Scheme and host only: connect-src takes an origin, not a path."""
    if not url.startswith("https://"):
        return ""
    return "https://" + url[8:].split("/", 1)[0]


class _Refus(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


Moderateur = Annotated[str, Depends(moderator)]


def create_app():
    app = FastAPI(title="ctester admin", docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def _entetes(request, call_next):
        reponse = await call_next(request)
        # Le code affiche vient des etudiants et la page detient un jeton de
        # moderateur : sans CSP, un fichier .c contenant du HTML deviendrait du XSS.
        # Le rendu passe par textContent, ceci en est la seconde ligne.
        reponse.headers["Content-Security-Policy"] = "; ".join([
            "default-src 'none'",
            "script-src 'self'",
            "style-src 'self' https://fonts.googleapis.com",
            "font-src https://fonts.gstatic.com",
            "connect-src 'self' " + _origine(config.OIDC_ISSUER),
            "base-uri 'none'",
            "form-action 'none'",
            "frame-ancestors 'none'",
        ]).strip()
        reponse.headers["Referrer-Policy"] = "no-referrer"
        reponse.headers["X-Content-Type-Options"] = "nosniff"
        return reponse

    @app.exception_handler(_Refus)
    async def _refus(request, exc):
        return JSONResponse({"error": exc.message}, status_code=exc.code)

    @app.get("/api/oidc")
    def api_oidc():
        """Public on purpose: the page needs it before it can sign anyone in."""
        return {"issuer": config.OIDC_ISSUER, "client_id": config.OIDC_CLIENT_ID}

    @app.get("/healthz")
    def healthz():
        return {"state": "ok"}

    @app.get("/")
    def index():
        return FileResponse(os.path.join(STATIC, "index.html"))

    @app.get("/admin.js")
    def script():
        return FileResponse(os.path.join(STATIC, "admin.js"),
                            media_type="application/javascript")

    @app.get("/auth.js")
    def auth():
        return FileResponse(os.path.join(STATIC, "auth.js"),
                            media_type="application/javascript")

    @app.get("/admin.css")
    def style():
        return FileResponse(os.path.join(STATIC, "admin.css"), media_type="text/css")

    @app.get("/api/overview")
    def api_overview(_: Moderateur):
        return _payload({
            "queue": overview.queue(),
            "release": overview.release(),
            "workers": overview.workers(),
            "windows": overview.windows(),
            "stats": state.read_run_stats(1),
        })

    @app.get("/api/runs")
    def api_runs(_: Moderateur, limit: int = 100, status: str = "",
                 exercise: str = "", worker: str = "", reveal: int = 0):
        """`account` is left out unless asked for: hiding a column while still shipping
        the name in the JSON would only be hiding it from the reader, not from the page."""
        runs = state.read_runs(limit, status or None, exercise or None, worker or None)
        if runs is not None and not reveal:
            runs = [{k: v for k, v in run.items() if k != "account"} for run in runs]
        return _payload({"runs": runs})

    @app.get("/api/code")
    def api_code(_: Moderateur, job_id: str = "", exercise_id: str = "",
                 account: str = ""):
        return JSONResponse(code_service.pour(job_id[:64], exercise_id[:64], account[:128]))

    @app.get("/api/stats")
    def api_stats(_: Moderateur, days: int = 7):
        days = max(1, min(days, 180))
        return _payload({
            "days": days,
            "stats": state.read_run_stats(days),
            "statuses": state.read_status_counts(days),
            "exercises": state.read_exercise_stats(days),
            "usage": state.read_usage(days),
            "activity": state.read_activity(days),
            "channels": state.read_channels(days),
        })

    return app


def _payload(body):
    """The dashboard says so plainly when the database is down, rather than showing zeros."""
    if any(value is None for value in body.values()):
        body = dict(body, degraded=True)
    return JSONResponse(body)


app = create_app()


if __name__ == "__main__":
    import uvicorn

    if not state.enabled():
        print("admin: CTESTER_DB_DSN is unset, only the queue and the release will show",
              file=sys.stderr)
    drain.start()
    uvicorn.run(
        app,
        host="0.0.0.0",  # noqa: S104 -- no published port; the proxy network reaches it
        port=PORT,
        workers=1,
        server_header=False,
        proxy_headers=True,
        access_log=False,
    )
