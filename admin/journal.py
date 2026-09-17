"""Reading the judge's run journal.

Standard library only: test_ctester.py imports this and runs on the host Python.
The judge appends one JSON object per line to results/runs-<date>.jsonl and never
rewrites one, so reading is a matter of remembering how far each file was read.
"""

import json

# What a record must carry for the admin app to store it; anything else is ignored.
FIELDS = ("job_id", "exercise_id", "account", "status", "kind", "duration_s",
          "queue_wait_s", "worker_id", "cache_hit", "reprises", "finished_at")

READ_MAX = 256 * 1024
LINES_MAX = 500


def parse_journal(blob, limit=LINES_MAX):
    """(records, consumed) for a chunk read at a known offset.

    A trailing fragment without its newline is a line the judge is still writing, or one
    torn by a full disk: it is left unconsumed so the next read sees it whole. A complete
    but unreadable line is consumed and dropped, otherwise it would block the cursor.
    """
    records = []
    consumed = 0
    for line in blob.split(b"\n")[:-1]:
        if len(records) >= limit:
            break
        consumed += len(line) + 1
        record = _record(line)
        if record is not None:
            records.append(record)
    return records, consumed


def _record(line):
    try:
        data = json.loads(line.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    job_id = data.get("job_id")
    if not isinstance(job_id, str) or not job_id:
        return None
    return {
        "job_id": job_id,
        "exercise_id": _text(data.get("exercise_id")),
        "account": _text(data.get("account")),
        "status": _text(data.get("status")),
        "kind": _text(data.get("kind")),
        "duration_s": _number(data.get("duration_s")),
        "queue_wait_s": _number(data.get("queue_wait_s")),
        "worker_id": _text(data.get("worker_id")),
        "cache_hit": bool(data.get("cache_hit")),
        "reprises": int(_number(data.get("reprises")) or 0),
        "finished_at": _number(data.get("finished_at")) or 0,
    }


def _text(value):
    return value[:128] if isinstance(value, str) else ""


def _number(value):
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None
