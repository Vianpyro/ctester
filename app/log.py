"""Log records in the OpenTelemetry Logs data model, one JSON object per line on stderr.

Standard library only: the worker, the bridge and test_ctester.py import it.
tests/vectors/log_record.json binds this format to the judge's (judge/src/log.rs).
"""

import contextvars
import datetime
import json
import logging
import os
import secrets
import sys
import time
import traceback

DEBUG, INFO, WARN, ERROR, FATAL = 5, 9, 13, 17, 21
SEVERITY_TEXT = {DEBUG: "DEBUG", INFO: "INFO", WARN: "WARN", ERROR: "ERROR", FATAL: "FATAL"}
_BY_NAME = {text.lower(): number for number, text in SEVERITY_TEXT.items()}
_FROM_LOGGING = ((logging.CRITICAL, FATAL), (logging.ERROR, ERROR), (logging.WARNING, WARN),
                 (logging.INFO, INFO), (0, DEBUG))

# Docker logs and journald outlive "Delete my data": no account, name, token, address, header,
# request body or code may enter a record. Any other key is dropped.
ATTRIBUTES = frozenset((
    "http.request.method", "http.route", "http.response.status_code",
    "error.type", "exception.type", "exception.stacktrace",
    "db.system.name", "server.address",
    "ctester.job.id", "ctester.exercise.id", "ctester.refusal", "ctester.queue.depth",
    "ctester.duration_ms", "ctester.ws.close_code", "ctester.revision",
    "ctester.exercises", "ctester.collections", "ctester.statements",
    "ctester.statements.cached", "ctester.channel", "ctester.channels",
    "ctester.interval_s", "ctester.feature.sign_in", "ctester.feature.forum",
    "ctester.feature.scratch", "ctester.feature.discord",
    "ctester.attempt", "ctester.cache.signature", "ctester.cache.source",
    "ctester.cache.pruned", "ctester.cache.left",
))

TEXT_MAX = 4096
STACK_MAX = 16384


def _level(name):
    return _BY_NAME.get(str(name).strip().lower().replace("warning", "warn"), INFO)


_resource = {"service.name": "ctester"}
_threshold = [_level(os.environ.get("CTESTER_LOG_LEVEL", "info"))]
_trace = contextvars.ContextVar("ctester_trace", default=None)


def setup(service, **resource):
    """Names the process and routes the standard `logging` records (uvicorn's) here too."""
    _resource.clear()
    _resource.update({"service.name": service}, **resource)
    _threshold[0] = _level(os.environ.get("CTESTER_LOG_LEVEL", "info"))
    root = logging.getLogger()
    root.handlers = [_Handler()]
    root.setLevel(logging.DEBUG if _threshold[0] <= DEBUG else logging.INFO)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).handlers = []
        logging.getLogger(name).propagate = True


def enabled(severity):
    return severity >= _threshold[0]


def begin_trace():
    """A fresh TraceId/SpanId for what follows in this context; pass the token to end_trace."""
    return _trace.set((secrets.token_hex(16), secrets.token_hex(8)))


def end_trace(token):
    _trace.reset(token)


def event(name, severity, body, attributes=None, exc=None, stack=False):
    if severity < _threshold[0]:
        return
    fields = dict(attributes or {})
    if exc is not None:
        fields["exception.type"] = _type_name(exc)
        if stack and exc.__traceback__ is not None:
            # Frames only: an exception's message can quote a value, such as a key in a
            # PostgreSQL error.
            fields["exception.stacktrace"] = "".join(
                traceback.format_tb(exc.__traceback__))[-STACK_MAX:]
    _write(record(name, severity, body, fields))


def record(name, severity, body, attributes, scope=None, now_ns=None):
    entry = {
        "Timestamp": str(time.time_ns() if now_ns is None else now_ns),
        "SeverityText": SEVERITY_TEXT[severity],
        "SeverityNumber": severity,
    }
    if name:
        entry["EventName"] = name
    entry["Body"] = str(body)[:TEXT_MAX]
    clean = {k: _value(v) for k, v in attributes.items() if k in ATTRIBUTES and v is not None}
    if clean:
        entry["Attributes"] = clean
    entry["Resource"] = dict(_resource)
    if scope:
        entry["InstrumentationScope"] = {"name": scope}
    trace = _trace.get()
    if trace:
        entry["TraceId"], entry["SpanId"] = trace
    return entry


def _value(value):
    if isinstance(value, (bool, int, float)):
        return value
    return str(value)[:STACK_MAX]


def _type_name(exc):
    kind = type(exc)
    module = kind.__module__
    return kind.__qualname__ if module == "builtins" else module + "." + kind.__qualname__


def _write(entry):
    stream = sys.stderr
    try:
        mode = os.environ.get("CTESTER_LOG_FORMAT", "") or (
            "text" if stream.isatty() else "json")
        if mode == "text":
            line = _text(entry)
        else:
            line = json.dumps(entry, ensure_ascii=False, separators=(",", ":"))
        stream.write(line + "\n")
        stream.flush()
    except (OSError, ValueError):
        pass


def _text(entry):
    when = datetime.datetime.fromtimestamp(int(entry["Timestamp"]) / 1e9, datetime.timezone.utc)
    parts = [when.strftime("%H:%M:%S"), entry["SeverityText"], entry.get("EventName", "-"),
             entry["Body"]]
    for key, value in entry.get("Attributes", {}).items():
        if key != "exception.stacktrace":
            parts.append("%s=%s" % (key, value))
    stack = entry.get("Attributes", {}).get("exception.stacktrace")
    return " ".join(parts) + ("\n" + stack.rstrip() if stack else "")


class _Handler(logging.Handler):
    """Records from other libraries: they carry no EventName and no attributes."""

    def emit(self, item):
        severity = next(s for floor, s in _FROM_LOGGING if item.levelno >= floor)
        if severity < _threshold[0]:
            return
        try:
            body = item.getMessage()
        except Exception:
            body = str(item.msg)
        fields = {}
        if item.exc_info and item.exc_info[1] is not None:
            fields["exception.type"] = _type_name(item.exc_info[1])
            fields["exception.stacktrace"] = "".join(
                traceback.format_tb(item.exc_info[2]))[-STACK_MAX:]
        _write(record(None, severity, body, fields, scope=item.name,
                      now_ns=int(item.created * 1e9)))
