"""Reading back the code behind a run, without storing any of it.

The spool's `files.json` is this run's exact code, until the judge sweeps it
(CTESTER_SWEEP_AFTER). After that, `exercise_state.sources` holds the student's latest
code for the exercise, which may be a later attempt. The verdict is swept with the spool
and is not kept anywhere else.
"""

import json
import os
import re

import config
import state
from services import catalog, spool

SOURCE_RUN = "run"
LAST_SOURCE = "last"

# The id becomes a path under results/: nothing but the judge's own format gets there.
JOB_RE = re.compile(r"\A[0-9a-f]{32}\Z")


def pour(job_id, exercise_id, account):
    """{source, files, at, result} -- `source` says which of the two answered, and the
    page must show it: passing off today's code as a Tuesday run would mislead."""
    result = _result(job_id)
    files = _from_spool(job_id, exercise_id)
    if files:
        return {"source": SOURCE_RUN, "files": files, "at": _when(job_id),
                "result": result}
    if account:
        last = state.read_submitted(account, exercise_id)
        if last and last["files"]:
            return {"source": LAST_SOURCE, "files": last["files"],
                    "at": last["at"], "result": result}
    return {"source": None, "files": {}, "at": None, "result": result}


def _result(job_id):
    """The verdict the student saw, or None once the judge has swept it."""
    if not JOB_RE.match(job_id):
        return None
    try:
        with open(os.path.join(config.RESULTS, job_id, "result.json"),
                  encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _from_spool(job_id, exercise_id):
    if not exercise_id or exercise_id.startswith(":"):
        return {}
    # preview=True: a closed or archived exercise is still the teacher's to read.
    entry = catalog.find_exercise(exercise_id, preview=True)
    if entry is None:
        return {}
    return spool.job_sources(job_id, entry)


def _when(job_id):
    try:
        stamp = os.path.getmtime(os.path.join(config.SPOOL, job_id, "job.json"))
    except OSError:
        return None
    import datetime as dt
    return dt.datetime.fromtimestamp(stamp, dt.timezone.utc).isoformat()
