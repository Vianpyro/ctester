"""What the dashboard shows. Everything here is read-only."""

import json
import os
import time
import urllib.request

import config
import state
from services import spool

WORKER_ALIVE = 300
WEB = os.environ.get("CTESTER_ADMIN_WEB_URL", "http://web:8000")


def windows():
    """How many browser windows the API has seen lately, signed in or not.

    `/live` also registers its caller, so this call subtracts itself, as ctester-pull does.
    """
    try:
        with urllib.request.urlopen(WEB + "/live?id=ctester-admin", timeout=2) as fh:
            data = json.load(fh)
    except Exception:  # noqa: BLE001 -- the web tier being down is not this page failing
        return {"open": None}
    n = data.get("n") if isinstance(data, dict) else None
    return {"open": max(0, n - 1) if isinstance(n, int) else None}


def queue(jobs=None):
    """`jobs` is a scan already made, so /api/live reads the spool once per tick."""
    if jobs is None:
        jobs = spool.scan_jobs()
    pending = sorted((stamp, name) for name, stamp, done in jobs if not done)
    # A claimed job has the judge's lock but no verdict yet: it is running, not waiting.
    running = sum(1 for _, name in pending if _claimed(name))
    now = time.time()
    oldest = (now - pending[0][0]) if pending else 0
    return {
        "pending": len(pending),
        "running": running,
        "waiting": len(pending) - running,
        "done_waiting": sum(1 for _, _, done in jobs if done),
        "oldest_s": round(oldest, 1),
        "eta_s": spool.eta_seconds(jobs, pending[-1][1]) if pending else 0,
        "workers_configured": config.WORKERS,
        "head": [_job(name, now - stamp) for stamp, name in pending[:10]],
    }


def _claimed(job_id):
    return os.path.exists(os.path.join(config.RESULTS, job_id, ".lock"))


def _job(job_id, waiting):
    exercise_id, owner = spool.job_metadata(job_id)
    return {"job_id": job_id, "exercise_id": exercise_id,
            "signed_in": owner is not None, "waiting_s": round(waiting, 1),
            "running": _claimed(job_id)}


def release():
    """The published catalogue the API is serving, straight from current.json."""
    pointer = os.path.join(config.PUBLISHED, "current.json")
    try:
        pulled = os.path.getmtime(os.path.join(config.PUBLISHED, ".pulled"))
    except OSError:
        pulled = None
    try:
        with open(pointer, encoding="utf-8") as fh:
            data = json.load(fh)
        stamp = os.path.getmtime(pointer)
    except (OSError, ValueError):
        return {"revision": None, "published_at": None, "exercises": None,
                "pulled_at": pulled}
    revision = data.get("revision") if isinstance(data, dict) else None
    return {"revision": revision, "published_at": stamp, "pulled_at": pulled,
            "exercises": _count(revision)}


def _count(revision):
    if not isinstance(revision, str) or not revision:
        return None
    try:
        with open(os.path.join(config.PUBLISHED, revision, "catalog.json"),
                  encoding="utf-8") as fh:
            catalogue = json.load(fh)
    except (OSError, ValueError):
        return None
    items = catalogue.get("exercises") if isinstance(catalogue, dict) else None
    return len(items) if isinstance(items, list) else None


def workers():
    rows = state.read_workers()
    if rows is None:
        return None
    now = time.time()
    for row in rows:
        row["alive"] = (now - _epoch(row["last_seen"])) < WORKER_ALIVE
    return rows


def _epoch(iso):
    try:
        import datetime
        return datetime.datetime.fromisoformat(iso).timestamp()
    except (ValueError, TypeError):
        return 0.0
