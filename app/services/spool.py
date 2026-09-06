"""The spool: the only channel between the API and the host's worker.

THE API WRITES AND READS FILES, it executes nothing. The worker runs on the
host, as root, and only reads this directory to launch a disposable container
under gVisor. This separation is what allows exposing the API to the Internet
without handing it the Docker socket.

`job.json` IS WRITTEN LAST, via an atomic rename: the worker only triggers on
its presence, and without this ordering it would read a half-written
`submission.c` and hand the student, one time in a hundred, a phantom
compile error that is not their fault.
"""

import json
import math
import os
import uuid

import config
from services.catalog import validate_files


def scan_jobs():
    """(job_id, timestamp, done) for every job in the spool.

    The timestamp comes from `job.json`'s mtime, which the worker never
    touches -- so the order seen here is the order the worker consumes, and
    the position shown to the student is true.
    """
    jobs = []
    try:
        entries = list(os.scandir(config.SPOOL))
    except OSError:
        return jobs
    for entry in entries:
        if not entry.is_dir():
            continue
        try:
            stamp = os.stat(os.path.join(entry.path, "job.json")).st_mtime
        except OSError:
            continue  # directory still being written: not yet a job
        done = os.path.exists(os.path.join(entry.path, "result.json"))
        jobs.append((entry.name, stamp, done))
    return jobs


def queue_position(jobs, job_id):
    """1-based rank of the job among those still waiting. 0 if it no longer waits."""
    pending = sorted((stamp, name) for name, stamp, done in jobs if not done)
    for rank, (_, name) in enumerate(pending, 1):
        if name == job_id:
            return rank
    return 0


# Written by the worker (`runner.enregistrer_duree`), read here: {id: [average, n]}.
# Absent until a job has run, and erasable without breaking anything -- the
# ETA then falls back to DUREE_INCONNUE.
DUREES = "durees.json"
# What a job costs when nothing has been measured for it yet, and no other
# exercise has an average either. Deliberately pessimistic: compilation
# (10 s) plus one run (5 s). Announcing shorter than the real thing is the
# only estimation error that gets noticed.
DUREE_INCONNUE = 15.0


def durees_moyennes():
    try:
        with open(os.path.join(config.SPOOL, DUREES), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: float(v[0]) for k, v in data.items()
            if isinstance(v, list) and len(v) == 2
            and isinstance(v[0], (int, float)) and v[0] > 0}


def eta_secondes(jobs, job_id):
    """Seconds before the verdict: the sum of jobs AHEAD, plus this one's own.

    Not a rank times a constant: a quiz grades instantly and a ten-case
    exercise pays for ten runs, so two queues of the same rank do not wait
    for the same thing. An exercise never measured takes the average of the
    others, and DUREE_INCONNUE failing that.
    """
    devant = sorted((stamp, name) for name, stamp, done in jobs if not done)
    moyennes = durees_moyennes()
    defaut = (sum(moyennes.values()) / len(moyennes)) if moyennes else DUREE_INCONNUE
    total = 0.0
    for _, name in devant:
        exercise_id, _owner = job_metadata(name)
        total += moyennes.get(exercise_id, defaut)
        if name == job_id:
            break
    else:
        return 0
    # Workers pop off the queue in parallel. `CTESTER_WORKERS` must reflect
    # the number of active `ctester-runner@` units: set too high, we promise
    # faster than the service can deliver.
    return int(math.ceil(total / max(1, config.WORKERS)))


def job_metadata(job_id):
    """The server-owned exercise and optional OIDC subject for one spool job.

    `owner` is written after validating the bearer token at submission time;
    it is never accepted from browser JSON.  Malformed/old jobs simply have no
    owner, so the job stays anonymous.
    """
    try:
        with open(os.path.join(config.SPOOL, job_id, "job.json"), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return "", None
    if not isinstance(data, dict):
        return "", None
    exercise_id = str(data.get("exercise_id", ""))
    owner = data.get("owner")
    if not isinstance(owner, str) or not 0 < len(owner) <= 128:
        owner = None
    return exercise_id, owner


def job_sources(job_id, entry):
    """The submitted source snapshot written to `exercise_state`.

    It is read only for a job whose owner was fixed by the API at submission.
    Quiz answers are not source files and intentionally keep the existing empty
    snapshot; compiled submissions use the same catalogue whitelist as every
    other path.
    """
    if entry.get("mode") == "quiz":
        return {}
    try:
        with open(os.path.join(config.SPOOL, job_id, "files.json"), encoding="utf-8") as fh:
            submitted = json.load(fh)
    except (OSError, ValueError):
        return {}
    files, message, _ = validate_files(entry, submitted)
    return files if message is None else {}


def ecrire_job(exercise_id, nom, blob, owner=None):
    """Writes the job and returns its id. `job.json` LAST, via rename.

    The worker only triggers on `job.json`'s presence. Without this ordering
    it would read a half-written `submission.c` and hand the student, one
    time in a hundred, a phantom compile error that is not their fault.

    `owner` COMES FROM THE VALIDATED TOKEN, never from the request body --
    that is what attaches an attempt to an account without letting it attach
    to someone else's. Bounded here too: it becomes half of a primary key.
    """
    job_id = uuid.uuid4().hex
    chemin = os.path.join(config.SPOOL, job_id)
    os.mkdir(chemin, 0o755)
    with open(os.path.join(chemin, nom), "wb") as fh:
        fh.write(blob)
    tmp = os.path.join(chemin, "job.json.tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        job = {"exercise_id": exercise_id}
        if isinstance(owner, str) and 0 < len(owner) <= 128:
            job["owner"] = owner
        json.dump(job, fh)
    os.replace(tmp, os.path.join(chemin, "job.json"))
    return job_id
