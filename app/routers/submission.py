import hmac
import json
import os
import re
import time

import config
import deps
import headers
import security
import state
from fastapi import APIRouter, Request
from schemas import SubmissionIn
from services import progress
from services import spool
from services.catalog import find_exercise, validate_files

JOB_RE = re.compile(r"\A[0-9a-f]{32}\Z")

router = APIRouter(tags=["submission"])


@router.post("/submit")
def submit(body: SubmissionIn, request: Request):
    # First and in constant time: nothing else may be observable without the key.
    if not config.KEY or not hmac.compare_digest(body.key, config.KEY):
        return headers.error(403, "clé de session invalide ou expirée")

    sub = security.current_user(request.headers)
    entry = find_exercise(body.exercise_id, security.is_moderator(sub))
    if entry is None:
        return headers.error(400, "TP inconnu")

    if entry.get("mode") == "quiz":
        if not isinstance(body.answers, dict):
            return headers.error(400, "réponses manquantes")
        trimmed = {str(k)[:64]: str(v)[:64]
                   for k, v in list(body.answers.items())[:500]}
        if not any(v.strip() for v in trimmed.values()):
            return headers.error(400, "aucune réponse saisie")
        name, blob = "answers.json", json.dumps(trimmed).encode()
    else:
        files, message, code = validate_files(entry, body.files)
        if message:
            return headers.error(code, message)
        if not any(v.strip() for v in files.values()):
            return headers.error(400, "soumission vide")
        name, blob = "files.json", json.dumps(files).encode()

    station = request.query_params.get("station", "")[:64]
    who = security.client_id(request.headers, deps.tcp_peer(request), station=station)
    with deps.lock:
        wait = (deps.signed_in_quota if sub else deps.quota).check(who, time.time())
        if wait:
            return headers.error(
                429, f"trop de soumissions -- réessaie dans {wait} s",
                retry_after=wait)
        # Counting and writing under the same lock, or concurrent requests overrun QUEUE_MAX.
        pending = sum(1 for _, _, finished in spool.scan_jobs() if not finished)
        if pending >= config.QUEUE_MAX:
            return headers.error(503, "file pleine -- réessaie dans une minute")
        job_id = spool.write_job(entry["id"], name, blob, sub,
                                 station=None if sub else security.station_tag(station))
    return {"id": job_id}


@router.get("/r/{job_id}")
def get_result(job_id: str):
    if not JOB_RE.match(job_id):
        return headers.error(400, "identifiant invalide")
    exercise_id, owner = spool.job_metadata(job_id)
    path = os.path.join(config.RESULTS, job_id, "result.json")
    try:
        with open(path, encoding="utf-8") as fh:
            result = json.load(fh)
    except OSError:
        result = None
    except ValueError:
        return headers.error(500, "verdict illisible", key="message",
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
