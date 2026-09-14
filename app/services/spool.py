import json
import math
import os
import uuid

import config
from services.catalog import validate_files


def scan_jobs():
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
            continue
        done = os.path.exists(os.path.join(entry.path, "result.json"))
        jobs.append((entry.name, stamp, done))
    return jobs


def queue_position(jobs, job_id):
    pending = sorted((stamp, name) for name, stamp, done in jobs if not done)
    for rank, (_, name) in enumerate(pending, 1):
        if name == job_id:
            return rank
    return 0


DURATIONS = "durees.json"
UNKNOWN_DURATION = 15.0


def average_durations():
    try:
        with open(os.path.join(config.SPOOL, DURATIONS), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: float(v[0]) for k, v in data.items()
            if isinstance(v, list) and len(v) == 2
            and isinstance(v[0], (int, float)) and v[0] > 0}


def eta_seconds(jobs, job_id):
    ahead = sorted((stamp, name) for name, stamp, done in jobs if not done)
    averages = average_durations()
    default = (sum(averages.values()) / len(averages)) if averages else UNKNOWN_DURATION
    total = 0.0
    for _, name in ahead:
        exercise_id, _owner = job_metadata(name)
        total += averages.get(exercise_id, default)
        if name == job_id:
            break
    else:
        return 0
    return int(math.ceil(total / max(1, config.WORKERS)))


def job_metadata(job_id):
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
    if entry.get("mode") == "quiz":
        return {}
    try:
        with open(os.path.join(config.SPOOL, job_id, "files.json"), encoding="utf-8") as fh:
            submitted = json.load(fh)
    except (OSError, ValueError):
        return {}
    files, message, _ = validate_files(entry, submitted)
    return files if message is None else {}


def write_job(exercise_id, name, blob, owner=None):
    job_id = uuid.uuid4().hex
    path = os.path.join(config.SPOOL, job_id)
    os.mkdir(path, 0o755)
    with open(os.path.join(path, name), "wb") as fh:
        fh.write(blob)
    # job.json last and atomically: workers only claim complete job directories.
    tmp = os.path.join(path, "job.json.tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        job = {"exercise_id": exercise_id}
        if isinstance(owner, str) and 0 < len(owner) <= 128:
            job["owner"] = owner
        json.dump(job, fh)
    os.replace(tmp, os.path.join(path, "job.json"))
    return job_id
