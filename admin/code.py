"""Reading back the code behind a run, without storing any of it.

Two sources, tried in order, because neither covers every case on its own:

1. The spool still holds `files.json` until the judge sweeps it
   (`CTESTER_SWEEP_AFTER`, 600 s). That is the code of *this* run, and it is there even
   for a student who was not signed in. During a lab -- when this page is actually
   being watched -- this is the source that answers.
2. `exercise_state.sources`, written on every attempt the student polled. Persistent,
   but it is their *latest* code for that exercise, not necessarily this run's.

Neither holds anything for a run the student never polled and that has been swept: the
poll is what writes the row.
"""

import os

import config
import state
from services import catalog, spool

SOURCE_RUN = "run"
LAST_SOURCE = "dernier"


def pour(job_id, exercise_id, account):
    """{source, files, at} -- `source` says which of the two answered, and the page
    must show it: passing off today's code as a Tuesday run would mislead."""
    files = _from_spool(job_id, exercise_id)
    if files:
        return {"source": SOURCE_RUN, "files": files, "at": _when(job_id)}
    if account:
        last = state.read_submitted(account, exercise_id)
        if last and last["files"]:
            return {"source": LAST_SOURCE, "files": last["files"],
                    "at": last["at"]}
    return {"source": None, "files": {}, "at": None}


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
