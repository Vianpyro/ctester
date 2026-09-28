"""Reading back the code behind a run, without storing any of it.

The spool's `files.json` is this run's exact code, until the judge sweeps it
(CTESTER_SWEEP_AFTER). After that, `exercise_state.sources` holds the student's latest
code for the exercise, which may be a later attempt. The verdict is swept with the spool
and is not kept anywhere else. A console session reads `src/` instead, then the notepad.
"""

import json
import os
import re
import stat

import config
import state
from services import catalog, spool

SOURCE_RUN = "run"
LAST_SOURCE = "last"
DRAFT_SOURCE = "draft"
CONSOLE = ":console"
CONSOLE_FILE_RE = re.compile(r"\A[A-Za-z0-9_]{1,32}\.[ch]\Z")

# The id becomes a path under results/: nothing but the judge's own format gets there.
JOB_RE = re.compile(r"\A[0-9a-f]{32}\Z")


def pour(job_id, exercise_id, account):
    """{source, files, at, result} -- `source` says which of the two answered, and the
    page must show it: passing off today's code as a Tuesday run would mislead."""
    result = _result(job_id)
    if exercise_id == CONSOLE:
        return _console(job_id, account, result)
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


def _console(job_id, account, result):
    """A console job's `src/` while the spool keeps it, then the account's saved notepad,
    which is what the student is typing now and may differ from what ran."""
    files = _console_sources(job_id)
    if files:
        return {"source": SOURCE_RUN, "files": files, "at": _when(job_id), "result": result}
    draft = state.read_scratch(account) if account else None
    if draft and draft["code"]:
        files = {"main.c": draft["code"]}
        if draft["header_name"]:
            files[draft["header_name"]] = draft["header"]
        return {"source": DRAFT_SOURCE, "files": files, "at": None, "result": result}
    return {"source": None, "files": {}, "at": None, "result": result}


def _console_sources(job_id):
    if not JOB_RE.match(job_id):
        return {}
    src = os.path.join(config.SPOOL, job_id, "src")
    try:
        names = sorted(os.listdir(src))
    except OSError:
        return {}
    files = {}
    for name in names:
        if not CONSOLE_FILE_RE.match(name):
            continue
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        try:
            fd = os.open(os.path.join(src, name), flags)
        except OSError:
            continue
        with os.fdopen(fd, "rb") as fh:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                continue
            blob = fh.read(config.MAX_CODE + 1)
        if len(blob) <= config.MAX_CODE:
            files[name] = blob.decode("utf-8", "replace")
    return files


def _from_spool(job_id, exercise_id):
    if not exercise_id or exercise_id.startswith(":"):
        return {}
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
