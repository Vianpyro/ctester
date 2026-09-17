"""What the dashboard shows. Everything here is read-only."""

import json
import os
import time

import config
import state
from services import spool

WORKER_ALIVE = 300


def queue():
    jobs = spool.scan_jobs()
    pending = sorted((stamp, name) for name, stamp, done in jobs if not done)
    now = time.time()
    oldest = (now - pending[0][0]) if pending else 0
    return {
        "pending": len(pending),
        "done_waiting": sum(1 for _, _, done in jobs if done),
        "oldest_s": round(oldest, 1),
        "eta_s": spool.eta_seconds(jobs, pending[-1][1]) if pending else 0,
        "workers_configured": config.WORKERS,
        "head": [_job(name, now - stamp) for stamp, name in pending[:10]],
    }


def _job(job_id, waiting):
    exercise_id, owner = spool.job_metadata(job_id)
    return {"job_id": job_id, "exercise_id": exercise_id,
            "signed_in": owner is not None, "waiting_s": round(waiting, 1)}


def release():
    """The published catalogue the API is serving, straight from current.json."""
    pointer = os.path.join(config.PUBLISHED, "current.json")
    try:
        with open(pointer, encoding="utf-8") as fh:
            data = json.load(fh)
        stamp = os.path.getmtime(pointer)
    except (OSError, ValueError):
        return {"revision": None, "published_at": None, "exercises": None}
    revision = data.get("revision") if isinstance(data, dict) else None
    return {"revision": revision, "published_at": stamp,
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
