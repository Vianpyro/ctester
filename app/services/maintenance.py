"""The update notice: whether the host announced a redeployment, and the stream that says so."""

import asyncio
import json
import os
import time

import config

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


def _state(on):
    return "event: state\ndata: %s\n\n" % json.dumps({"maintenance": on})


async def stream(max_s=None, tick=TICK):
    """Server-sent `state` events, on connect and on every change.

    The stream ends after max_s so connections turn over; the page reconnects."""
    deadline = time.monotonic() + (STREAM_MAX if max_s is None else max_s)
    last = _cached()
    last_sent = time.monotonic()
    yield "retry: 2000\n\n" + _state(last)
    while time.monotonic() < deadline:
        await asyncio.sleep(tick)
        on = _cached()
        now = time.monotonic()
        if on != last:
            yield _state(on)
            last, last_sent = on, now
        elif now - last_sent >= HEARTBEAT:
            yield ": \n\n"
            last_sent = now
