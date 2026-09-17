#!/usr/bin/env python3

"""The teacher's dashboard: a separate app, reachable only on the LAN.

It has no sign-in of its own. The proxy in front of it is the boundary, so its host must
carry an access list restricted to the LAN -- see docs/operations.md. Nothing here writes
to the service: the only table it fills is its own copy of the judge's run journal.
"""

import os
import sys

import config
import drain
import overview
import state
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
PORT = int(os.environ.get("CTESTER_ADMIN_PORT", "8001"))


def create_app():
    app = FastAPI(title="ctester admin", docs_url=None, redoc_url=None, openapi_url=None)

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

    @app.get("/admin.css")
    def style():
        return FileResponse(os.path.join(STATIC, "admin.css"), media_type="text/css")

    @app.get("/api/overview")
    def api_overview():
        return _payload({
            "queue": overview.queue(),
            "release": overview.release(),
            "workers": overview.workers(),
            "windows": overview.windows(),
            "stats": state.read_run_stats(1),
        })

    @app.get("/api/runs")
    def api_runs(limit: int = 100, status: str = "", exercise: str = "",
                 worker: str = ""):
        return _payload({"runs": state.read_runs(limit, status or None,
                                                 exercise or None, worker or None)})

    @app.get("/api/stats")
    def api_stats(days: int = 7):
        days = max(1, min(days, 180))
        return _payload({
            "days": days,
            "stats": state.read_run_stats(days),
            "statuses": state.read_status_counts(days),
            "exercises": state.read_exercise_stats(days),
            "usage": state.read_usage(days),
            "activity": state.read_activity(days),
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
