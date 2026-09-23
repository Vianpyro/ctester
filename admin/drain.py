"""Moving the judge's run journal into PostgreSQL.

The files are read-only here, so a byte offset per file tracks progress; re-reading is
harmless because the insert skips known job ids.
"""

import datetime
import glob
import os
import threading
import time

import config
import state
from journal import LINES_MAX, READ_MAX, parse_journal

PATTERN = "runs-*.jsonl"
EVERY = 30

# The drain's last result, read by /api/overview. A stalled ingestion must show:
# otherwise the dashboard freezes with nothing to say so.
health = {"ok": True, "since": None, "ingested": 0}

# Set by /api/live the moment a verdict lands in results/: the pass runs then, not up to
# EVERY seconds later, which is how a run reaches the dashboard within a second. EVERY
# stays the fallback for a verdict nobody was watching.
wake = threading.Event()


def journal_files():
    """Sorted by name, which is sorted by date: the judge names them after the day."""
    return sorted(glob.glob(os.path.join(config.RESULTS, PATTERN)))


def drain_once():
    """Returns the number of runs stored, or None when the database is unavailable."""
    offsets = state.journal_offsets()
    if offsets is None:
        return None
    paths = journal_files()
    # Once per pass, not per file: a pass with nothing to read still prunes.
    if state.forget_journal_files([os.path.basename(path) for path in paths]) is None:
        return None
    stored = 0
    for path in paths:
        name = os.path.basename(path)
        start = offsets.get(name, 0)
        try:
            size = os.path.getsize(path)
        except OSError:
            continue
        # A file that shrank was replaced, so its offset means nothing any more.
        if size < start:
            start = 0
        if size == start:
            continue
        try:
            with open(path, "rb") as fh:
                fh.seek(start)
                blob = fh.read(READ_MAX)
        except OSError:
            continue
        records, consumed = parse_journal(blob)
        if not consumed:
            continue
        written = state.write_runs(_rows(records), name, start + consumed)
        if written is None:
            return None
        stored += len(records)
        # A full read means there is more behind it; the next pass takes it.
        if len(records) >= LINES_MAX or consumed >= READ_MAX:
            break
    return stored


def _rows(records):
    rows = []
    for record in records:
        row = dict(record)
        row["finished_at"] = datetime.datetime.fromtimestamp(
            row["finished_at"], datetime.timezone.utc)
        rows.append(row)
    return rows


def run_forever(every=EVERY):
    while True:
        # Cleared before the pass, not after: a verdict landing during it wakes the next.
        wake.clear()
        try:
            _record(drain_once())
        except Exception as exc:  # noqa: BLE001 -- a bad line must not stop the loop
            _record(None, repr(exc))
        wake.wait(every)


def _record(stored, exception=""):
    """A failing pass is reported once, not on every tick."""
    if stored is None:
        if health["ok"]:
            print("admin: the journal is no longer ingested" + (": " + exception if exception
                  else " (the database refused the write; is the schema up to date?)"), flush=True)
            health.update(ok=False, since=time.time())
        return
    if not health["ok"]:
        print("admin: journal ingestion restored", flush=True)
    health.update(ok=True, since=None)
    health["ingested"] += stored


def start():
    """One thread, so drains never overlap and need no lock of their own."""
    if not state.enabled():
        print("admin: no CTESTER_DB_DSN, the run journal will not be ingested", flush=True)
        return None
    thread = threading.Thread(target=run_forever, name="drain", daemon=True)
    thread.start()
    return thread
