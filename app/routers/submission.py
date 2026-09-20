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

# Request-shape bounds, not settings: a matching or ordering answer is a list or a map of
# option texts, so one level of nesting is admitted and nothing deeper.
MAX_ANSWERS = 500
MAX_KEY = 64
MAX_VALUE = 256
MAX_ITEMS = 40
MAX_ANSWERS_BYTES = 20000
# A page shows a handful of exercises at most and they share one cooldown slot, so the
# batch needs its own bounds: per exercise above, and in total here. Kept under the
# request-body cap (config.MAX_CODE + 4096) so it is a bound that can actually be reached.
MAX_BATCH = 8
MAX_BATCH_BYTES = 40000


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


def _payload(entry, answers, files):
    """What one exercise contributes to the spool: (name, blob) or (None, refusal)."""
    if entry.get("mode") == "quiz":
        if not isinstance(answers, dict):
            return None, headers.error(400, "réponses manquantes")
        trimmed = {str(k)[:MAX_KEY]: _one(v)
                   for k, v in list(answers.items())[:MAX_ANSWERS]}
        if not any(_filled(v) for v in trimmed.values()):
            return None, headers.error(400, "aucune réponse saisie")
        blob = json.dumps(trimmed).encode()
        if len(blob) > MAX_ANSWERS_BYTES:
            return None, headers.error(413, "réponses trop longues")
        return ("answers.json", blob), None
    found, message, code = validate_files(entry, files)
    if message:
        return None, headers.error(code, message)
    if not any(v.strip() for v in found.values()):
        return None, headers.error(400, "soumission vide")
    return ("files.json", json.dumps(found).encode()), None


def _asked(body):
    """The exercises this request covers, batch or not. None means a malformed batch."""
    if body.items is None:
        return [(body.exercise_id, body.answers, body.files)]
    if not body.items or len(body.items) > MAX_BATCH:
        return None
    asked = []
    for item in body.items:
        if not isinstance(item, dict):
            return None
        asked.append((str(item.get("exercise_id", "")),
                      item.get("answers"), item.get("files")))
    return asked


@router.post("/submit")
def submit(body: SubmissionIn, request: Request):
    # First and in constant time: nothing else may be observable without the key.
    if not config.KEY or not hmac.compare_digest(body.key, config.KEY):
        return headers.error(403, "clé de session invalide ou expirée")

    asked = _asked(body)
    if asked is None:
        return headers.error(400, "requête malformée")

    # Everything is resolved and bounded before the quota is touched: a batch is accepted
    # whole or refused whole, so a student never pays a slot for a half-written page.
    sub = security.current_user(request.headers)
    moderator = security.is_moderator(sub)
    ready, total = [], 0
    for exercise_id, answers, files in asked:
        entry = find_exercise(exercise_id, moderator)
        if entry is None:
            return headers.error(400, "TP inconnu")
        payload, refusal = _payload(entry, answers, files)
        if refusal is not None:
            return refusal
        total += len(payload[1])
        ready.append((entry, payload[0], payload[1]))
    if total > MAX_BATCH_BYTES:
        return headers.error(413, "réponses trop longues")

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
        if pending + len(ready) > config.QUEUE_MAX:
            return headers.error(503, "file pleine -- réessaie dans une minute")
        tag = None if sub else security.station_tag(station)
        ids = [spool.write_job(entry["id"], name, blob, sub, station=tag)
               for entry, name, blob in ready]
    return {"ids": ids} if body.items is not None else {"id": ids[0]}


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
