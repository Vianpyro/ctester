"""The update notice: whether the host announced a redeployment, and the stream that says so,
along with the moderators' announcement."""

import asyncio
import json
import os
import time

import config
from services import announcement

TICK = 1.0
HEARTBEAT = 20.0
STREAM_MAX = 600.0

# One stat a second for every open tab together, not one per tab.
_cache = {"at": None, "on": False}


def active(now=None):
    now = time.time() if now is None else now
    if not config.MAINTENANCE_FLAG:
        return False
    try:
        age = now - os.stat(config.MAINTENANCE_FLAG).st_mtime
    except OSError:
        return False
    return age < config.MAINTENANCE_MAX


def _cached():
    now = time.monotonic()
    if _cache["at"] is None or now - _cache["at"] >= TICK:
        _cache["at"], _cache["on"] = now, active()
    return _cache["on"]


def _state(on, note):
    return "event: state\ndata: %s\n\n" % json.dumps({"maintenance": on, "announcement": note})


async def _seen():
    if not announcement.loaded():
        await asyncio.to_thread(announcement.load)
    return _cached(), announcement.current()


async def stream(max_s=None, tick=TICK):
    """Server-sent `state` events, on connect and on every change.

    The stream ends after max_s so connections turn over; the page reconnects."""
    deadline = time.monotonic() + (STREAM_MAX if max_s is None else max_s)
    last = await _seen()
    last_sent = time.monotonic()
    yield "retry: 2000\n\n" + _state(*last)
    while time.monotonic() < deadline:
        await asyncio.sleep(tick)
        seen = await _seen()
        now = time.monotonic()
        if seen != last:
            yield _state(*seen)
            last, last_sent = seen, now
        elif now - last_sent >= HEARTBEAT:
            yield ": \n\n"
            last_sent = now
