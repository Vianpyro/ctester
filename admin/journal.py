"""Reading the judge's append-only run journal, results/runs-<date>.jsonl.

Standard library only: test_ctester.py imports this.
"""

import json

# What a record must carry for the admin app to store it; anything else is ignored.
FIELDS = ("job_id", "exercise_id", "account", "station", "status", "passed", "total", "kind",
          "duration_s", "queue_wait_s", "worker_id", "cache_hit", "reprises", "finished_at")

READ_MAX = 256 * 1024
LINES_MAX = 500


def parse_journal(blob, limit=LINES_MAX):
    """(records, consumed) for a chunk read at a known offset.

    A last line without its newline is still being written and is left for the next read;
    a complete but unreadable line is dropped so it cannot block the cursor.
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
        "station": _station(data.get("station")),
        "status": _text(data.get("status")),
        "passed": _count(data.get("passed")),
        "total": _count(data.get("total")),
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


def _station(value):
    text = _text(value)
    return text if len(text) <= 16 and all(c in "0123456789abcdef" for c in text) else ""


def _count(value):
    number = _number(value)
    return int(number) if number is not None and 0 <= number < 2 ** 31 else None


def _number(value):
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None
