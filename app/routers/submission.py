import hmac
import json
import os
import re
import time

import config
import deps
import headers
import log
import security
import state
from fastapi import APIRouter, Request
from schemas import SubmissionIn
from services import progress
from services import spool
from services.catalog import find_exercise, validate_files

JOB_RE = re.compile(r"\A[0-9a-f]{32}\Z")

# Request-shape bounds, not settings: a matching or ordering answer is a list or a map of
# option texts, so one level of nesting is admitted and nothing deeper.
MAX_ANSWERS = 500
MAX_KEY = 64
MAX_VALUE = 256
MAX_ITEMS = 40
MAX_ANSWERS_BYTES = 20000


def _one(value):
    """One submitted answer: text, a list of texts, or a map of text to text. Anything
    deeper is flattened by str(), which is the boundary the worker is allowed to trust."""
    if isinstance(value, list):
        return [str(item)[:MAX_VALUE] for item in value[:MAX_ITEMS]]
    if isinstance(value, dict):
        return {str(k)[:MAX_VALUE]: str(v)[:MAX_VALUE]
                for k, v in list(value.items())[:MAX_ITEMS]}
    return str(value)[:MAX_VALUE]


def _filled(value):
    if isinstance(value, list):
        return any(str(item).strip() for item in value)
    if isinstance(value, dict):
        return any(str(chosen).strip() for chosen in value.values())
    return value.strip()

router = APIRouter(tags=["submission"])


@router.post("/submit")
def submit(body: SubmissionIn, request: Request):
    # First and in constant time: nothing else may be observable without the key.
    if not config.KEY or not hmac.compare_digest(body.key, config.KEY):
        return headers.error(403, "invalid_session_key")

    sub = security.current_user(request.headers)
    entry = find_exercise(body.exercise_id, security.is_moderator(sub))
    if entry is None:
        return headers.error(400, "unknown_exercise")

    if entry.get("mode") == "quiz":
        if not isinstance(body.answers, dict):
            return headers.error(400, "answers_missing")
        trimmed = {str(k)[:MAX_KEY]: _one(v)
                   for k, v in list(body.answers.items())[:MAX_ANSWERS]}
        if not any(_filled(v) for v in trimmed.values()):
            return headers.error(400, "no_answer")
        blob = json.dumps(trimmed).encode()
        if len(blob) > MAX_ANSWERS_BYTES:
            return headers.error(413, "answers_too_long")
        name = "answers.json"
    else:
        files, message, code = validate_files(entry, body.files)
        if message:
            return headers.error(code, message)
        if not any(v.strip() for v in files.values()):
            return headers.error(400, "empty_submission")
        name, blob = "files.json", json.dumps(files).encode()

    station = request.query_params.get("station", "")[:64]
    who = security.client_id(request.headers, deps.tcp_peer(request), station=station)
    with deps.lock:
        wait = (deps.signed_in_quota if sub else deps.quota).check(who, time.time())
        if wait:
            return headers.error(
                429, "too_many_submissions", params={"wait": wait},
                retry_after=wait)
        # Counting and writing under the same lock, or concurrent requests overrun QUEUE_MAX.
        pending = sum(1 for _, _, finished in spool.scan_jobs() if not finished)
        if pending >= config.QUEUE_MAX:
            return headers.error(503, "queue_full")
        job_id = spool.write_job(entry["id"], name, blob, sub,
                                 station=None if sub else security.station_tag(station))
    log.event("job.enqueued", log.INFO, "job queued for " + entry["id"], {
        "ctester.job.id": job_id,
        "ctester.exercise.id": entry["id"],
        "ctester.queue.depth": pending + 1,
    })
    return {"id": job_id}


@router.get("/r/{job_id}")
def get_result(job_id: str):
    if not JOB_RE.match(job_id):
        return headers.error(400, "invalid_id")
    exercise_id, owner = spool.job_metadata(job_id)
    path = os.path.join(config.RESULTS, job_id, "result.json")
    try:
        with open(path, encoding="utf-8") as fh:
            result = json.load(fh)
    except OSError:
        result = None
    except ValueError:
        return headers.error(500, "verdict_unreadable", key="message",
                             state="error")

    if result is not None:
        if owner is not None and exercise_id and isinstance(result, dict):
            _record(owner, exercise_id, job_id, result)
        return result

    if os.path.exists(os.path.join(config.RESULTS, job_id, ".lock")):
        return {"state": "running"}
    jobs = spool.scan_jobs()
    rank = spool.queue_position(jobs, job_id)
    if rank:
        return {"state": "queued", "position": rank,
                "eta": spool.eta_seconds(jobs, job_id)}
    return headers.error(404, "gone", key="state")


def _record(owner, exercise_id, job_id, result):
    state.write_practice_attempt(owner, job_id, exercise_id, result)
    entry = find_exercise(exercise_id, security.is_moderator(owner))
    if entry is None:
        return
    solved = (result.get("status") == "ok"
              and result.get("total", 0) > 0
              and result.get("passed") == result.get("total"))
    state.write_state(owner, exercise_id, "solved" if solved else "attempted",
                     spool.job_sources(job_id, entry))
    # Team members share one document, so personal XP would pay for the same work
    # several times. Verifications record mastery evidence instead of XP.
    if entry.get("assignment"):
        return
    if entry.get("verification"):
        progress.record_verification(owner, entry, job_id, solved)
    elif solved:
        progress.reward(owner, entry, job_id)
