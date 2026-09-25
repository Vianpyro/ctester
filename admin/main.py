#!/usr/bin/env python3

"""The teacher's dashboard, a separate app on the LAN.

Every /api route demands a moderator's OIDC token on top of the proxy's access list
(see docs/operations.md). The only table it writes is its copy of the run journal.
"""

import asyncio
import json
import os
import time
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import code as code_service
import config
import drain
import log
import overview
import security
import state
from fastapi import Depends, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from services import spool

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
PORT = int(os.environ.get("CTESTER_ADMIN_PORT", "8001"))


def moderator(request: Request) -> str:
    """The same test as the student API: the account comes from the validated token,
    never from the request."""
    if not security.oidc_enabled():
        raise _Refusal(503, "la connexion n'est pas configurée sur ce déploiement")
    if not security.userinfo_url():
        raise _Refusal(503, "l'API n'atteint pas l'IdP : vérifie que le conteneur"
                          " résout CTESTER_OIDC_ISSUER (extra_hosts)")
    sub = security.current_user(request.headers)
    if sub is None:
        raise _Refusal(401, "connexion requise ou expirée")
    if not security.is_moderator(sub):
        raise _Refusal(403, "réservé à l'enseignant")
    return sub


def _origin(url):
    """Scheme and host only: connect-src takes an origin, not a path."""
    if not url.startswith("https://"):
        return ""
    return "https://" + url[8:].split("/", 1)[0]


class _Refusal(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


Moderator = Annotated[str, Depends(moderator)]


def create_app():
    app = FastAPI(title="ctester admin", docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def _headers(request, call_next):
        response = await call_next(request)
        # The code shown comes from students and the page holds a moderator token:
        # without a CSP, a .c file containing HTML would become XSS. Rendering goes
        # through textContent; this is the second line of defense.
        response.headers["Content-Security-Policy"] = "; ".join([
            "default-src 'none'",
            "script-src 'self'",
            "style-src 'self' https://fonts.googleapis.com",
            "font-src https://fonts.gstatic.com",
            "connect-src 'self' " + _origin(config.OIDC_ISSUER),
            "base-uri 'none'",
            "form-action 'none'",
            "frame-ancestors 'none'",
        ]).strip()
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.exception_handler(_Refusal)
    async def _refusal(request, exc):
        return JSONResponse({"error": exc.message}, status_code=exc.code)

    @app.get("/api/oidc")
    def api_oidc():
        """Public on purpose: the page needs it before it can sign anyone in."""
        return {"issuer": config.OIDC_ISSUER, "client_id": config.OIDC_CLIENT_ID}

    @app.get("/healthz")
    def healthz():
        return {"state": "ok"}

    # Revalidated on every load: without it the browser guesses a lifetime from the
    # file's age, and a deploy can leave an old admin.js running against a new page.
    fresh = {"Cache-Control": "no-cache"}

    @app.get("/")
    def index():
        return FileResponse(os.path.join(STATIC, "index.html"), headers=fresh)

    @app.get("/admin.js")
    def script():
        return FileResponse(os.path.join(STATIC, "admin.js"),
                            media_type="application/javascript", headers=fresh)

    @app.get("/auth.js")
    def auth():
        return FileResponse(os.path.join(STATIC, "auth.js"),
                            media_type="application/javascript", headers=fresh)

    @app.get("/admin.css")
    def style():
        return FileResponse(os.path.join(STATIC, "admin.css"), media_type="text/css",
                            headers=fresh)

    @app.get("/api/overview")
    def api_overview(_: Moderator):
        return _payload({
            "queue": overview.queue(),
            "release": overview.release(),
            "workers": overview.workers(),
            "windows": overview.windows(),
            "ingestion": dict(drain.health),
        })

    @app.get("/api/live")
    async def api_live(_: Moderator):
        """Server-sent `queue` and `runs` events.

        The stream ends after LIVE_MAX so the reconnect checks the token again. It is
        `async def` because a `def` would hold a threadpool thread per open tab."""
        return StreamingResponse(_live(), media_type="text/event-stream", headers={
            "Cache-Control": "no-cache",
            # Nginx buffers proxied responses by default; this header turns it off for
            # this one, with no change to the proxy host.
            "X-Accel-Buffering": "no",
        })

    @app.get("/api/runs")
    def api_runs(_: Moderator, limit: int = 100, status: str = "",
                 exercise: str = "", worker: str = "", reveal: int = 0):
        """`account` is left out unless asked for, by the query itself: hiding a column
        while still shipping the name in the JSON would only hide it from the reader."""
        return _payload({"runs": state.read_runs(
            limit, status or None, exercise or None, worker or None, bool(reveal))})

    @app.get("/api/code")
    def api_code(_: Moderator, job_id: str = "", exercise_id: str = "",
                 account: str = ""):
        return JSONResponse(code_service.pour(job_id[:64], exercise_id[:64], account[:128]))

    @app.get("/api/stats")
    def api_stats(_: Moderator, days: int = 7, tz: str = "UTC"):
        days = max(1, min(days, 180))
        return _payload({
            "days": days,
            "stats": state.read_run_stats(days),
            "statuses": state.read_status_counts(days),
            "exercises": state.read_exercise_stats(days),
            "usage": state.read_usage(days),
            "activity": state.read_activity(days, _zone(tz)),
            "channels": state.read_channels(days),
        })

    return app


# The page sends its own IANA zone. An unknown one would abort the whole stats query,
# so it falls back rather than taking the panel down with it.
def _zone(name):
    try:
        ZoneInfo(name[:64])
    except (ZoneInfoNotFoundError, ValueError):
        return "UTC"
    return name[:64]


LIVE_TICK = 0.25
LIVE_MAX = 120
LIVE_HEARTBEAT = 15


def _event(name, data):
    return "event: %s\ndata: %s\n\n" % (name, json.dumps(data, separators=(",", ":")))


async def _live():
    """Jobs last under a second, so a slow poll misses them; the spool is scanned every
    LIVE_TICK and only changes are sent."""
    deadline = time.monotonic() + LIVE_MAX
    last_key = None
    last_sent = 0.0
    ingested = drain.health["ingested"]
    finished = None
    yield "retry: 1000\n\n"
    while time.monotonic() < deadline:
        jobs = await asyncio.to_thread(spool.scan_jobs)
        done = {name for name, _, is_done in jobs if is_done}
        # A new verdict: have the drain store it now rather than on its next pass.
        if finished is not None and done - finished:
            drain.wake.set()
        finished = done
        q = await asyncio.to_thread(overview.queue, jobs)
        key = (q["pending"], q["running"], q["done_waiting"],
               tuple((j["job_id"], j["running"]) for j in q["head"]))
        now = time.monotonic()
        # While something waits, once a second anyway: the waiting times must move.
        if key != last_key or (q["pending"] and now - last_sent >= 1):
            yield _event("queue", q)
            last_key, last_sent = key, now
        elif now - last_sent >= LIVE_HEARTBEAT:
            yield ": \n\n"
            last_sent = now
        if drain.health["ingested"] != ingested:
            ingested = drain.health["ingested"]
            yield _event("runs", {"ingested": ingested})
        await asyncio.sleep(LIVE_TICK)


def _payload(body):
    """The dashboard says so plainly when the database is down, rather than showing zeros."""
    if any(value is None for value in body.values()):
        body = dict(body, degraded=True)
    return JSONResponse(body)


app = create_app()


if __name__ == "__main__":
    import uvicorn

    log.setup("ctester-admin")
    log.event("service.start", log.INFO, "listening on port %d" % PORT)
    drain.start()
    uvicorn.run(
        app,
        host="0.0.0.0",  # noqa: S104 -- no published port; the proxy network reaches it
        port=PORT,
        workers=1,
        server_header=False,
        proxy_headers=True,
        access_log=False,
        log_config=None,
    )
