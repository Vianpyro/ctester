"""The moderators' announcement: one at a time, shown in every tab, signed in or not."""

import time
import uuid

import state

MAX_CHARS = 500
HOURS = (1, 6, 24, 72)
# While the database is down, the event stream retries the first read this often.
RETRY = 30.0

# One uvicorn worker: once read, this copy is the truth, and a publication replaces it.
_cache = {"row": None, "tried": None}


def loaded():
    return _cache["row"] is not None


def load(now=None):
    """Blocking: the event stream calls it through a thread, and only until it succeeds."""
    now = time.monotonic() if now is None else now
    if loaded() or (_cache["tried"] is not None and now - _cache["tried"] < RETRY):
        return
    _cache["tried"] = now
    row = state.announcement_latest()
    if row is not None:
        _cache["row"] = row


def current(now=None):
    row = _cache["row"] or {}
    if not row.get("text"):
        return None
    expires = row.get("expires_at")
    if expires is not None and (time.time() if now is None else now) >= expires:
        return None
    return {"id": row["id"], "text": row["text"]}


def publish(raw, hours):
    """None, or the refusal as (status, key). An empty text takes the announcement down."""
    if not isinstance(raw, str):
        return (400, "message_missing")
    text = raw.replace("\r\n", "\n")
    text = "".join(c for c in text if c in "\n\t" or c >= " ").strip()
    if len(text) > MAX_CHARS:
        return (400, ("announcement_too_long", {"max": MAX_CHARS}))
    if hours not in HOURS:
        return (400, "invalid_duration")
    row = {"id": uuid.uuid4().hex, "text": text,
           "expires_at": time.time() + hours * 3600 if text else None}
    if state.announcement_write(row["id"], row["text"], row["expires_at"]) is None:
        return (503, "db_down")
    _cache["row"] = row
    return None
