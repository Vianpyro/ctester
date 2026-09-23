import codecs
import json
import os
import re

import config
from services.source import canonicalize
from services.spool import new_job_id

try:
    import fcntl
except ImportError:
    fcntl = None

KIND = "console"
# The judge's gate::valid_header_name and frontend lib/domain/scratchHeader.ts apply the same rule.
HEADER_RE = re.compile(r"\A[A-Za-z0-9_]{1,32}\.h\Z")


def validate_scratch(code):
    if not isinstance(code, str):
        return None, "bloc-notes manquant", 400
    code = canonicalize(code)
    if len(code.encode("utf-8")) > config.MAX_CODE:
        return None, ("notepad_too_big", {"kb": config.MAX_CODE // 1024}), 413
    return code, None, 200


def validate_header(name, text):
    """An empty name means no header, and then its text must be empty too."""
    if not isinstance(name, str) or not isinstance(text, str):
        return None, None, "malformed_header", 400
    if not name:
        if text:
            return None, None, "header_without_name", 400
        return "", "", None, 200
    if not HEADER_RE.match(name):
        return None, None, "invalid_header_name", 400
    text = canonicalize(text)
    if len(text.encode("utf-8")) > config.MAX_CODE:
        return None, None, ("header_too_big", {"kb": config.MAX_CODE // 1024}), 413
    return name, text, None, 200


class Session:
    def __init__(self, job_id, path, lock):
        self.job_id = job_id
        self.path = path
        # Keystrokes go into the spool; everything the judge sends back is read from RESULTS.
        self.results = os.path.join(config.RESULTS, job_id)
        self._lock = lock
        self._offsets = {"build": 0, "out": 0}
        self._decoders = {name: codecs.getincrementaldecoder("utf-8")("replace")
                          for name in ("build", "out")}
        self._input_bytes = 0

    def close(self):
        # Releasing the flock on `alive` is what tells the worker to stop the container.
        try:
            os.close(self._lock)
        except OSError:
            pass

    def write_input(self, text):
        chunk = text.encode("utf-8", "replace")
        if self._input_bytes + len(chunk) > config.SCRATCH_IN_MAX:
            return False
        try:
            with open(os.path.join(self.path, "in"), "ab", buffering=0) as fh:
                fh.write(chunk)
        except OSError:
            return False
        self._input_bytes += len(chunk)
        return True

    def close_input(self):
        try:
            with open(os.path.join(self.path, "eof"), "wb"):
                pass
        except OSError:
            pass

    def read_output(self, name):
        try:
            with open(os.path.join(self.results, name), "rb") as fh:
                chunk = os.pread(fh.fileno(), 65536, self._offsets[name])
        except OSError:
            return ""
        if not chunk:
            return ""
        self._offsets[name] += len(chunk)
        return self._decoders[name].decode(chunk)

    def status(self):
        try:
            with open(os.path.join(self.results, "state.json"),
                      encoding="utf-8") as fh:
                status = json.load(fh)
        except (OSError, ValueError):
            return None
        return status if isinstance(status, dict) else None

    def is_claimed(self):
        return os.path.exists(os.path.join(self.results, ".lock"))

    def worker_alive(self):
        return _lock_held(os.path.join(self.results, "claim"))


def open_session(code, header_name="", header=""):
    if fcntl is None:
        raise RuntimeError("the console needs flock (POSIX only)")

    job_id = new_job_id()
    path = os.path.join(config.SPOOL, job_id)
    os.mkdir(path, 0o755)
    os.mkdir(os.path.join(path, "src"), 0o755)
    with open(os.path.join(path, "src", "main.c"), "w",
              encoding="utf-8") as fh:
        fh.write(code)
    job = {"kind": KIND}
    if header_name:
        with open(os.path.join(path, "src", header_name), "w",
                  encoding="utf-8") as fh:
            fh.write(header)
        job["header"] = header_name
    lock = os.open(os.path.join(path, "alive"),
                   os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(lock)
        raise
    # job.json goes last, atomically: the worker only picks up complete jobs.
    # It carries no owner or exercise, so nothing identifying reaches the worker.
    tmp = os.path.join(path, "job.json.tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(job, fh)
    os.replace(tmp, os.path.join(path, "job.json"))
    return Session(job_id, path, lock)


def _lock_held(path):
    # Read-only: `claim` sits on a read-only mount and flock does not need write access.
    # A missing lock file is not held.
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return True
    else:
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    finally:
        os.close(fd)
