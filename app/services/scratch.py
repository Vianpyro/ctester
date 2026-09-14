import codecs
import json
import os

import config
from services.source import canonicalize
from services.spool import new_job_id

try:
    import fcntl
except ImportError:
    fcntl = None

KIND = "console"


def validate_scratch(code):
    if not isinstance(code, str):
        return None, "bloc-notes manquant", 400
    code = canonicalize(code)
    if len(code.encode("utf-8")) > config.MAX_CODE:
        return None, "bloc-notes > %d Ko" % (config.MAX_CODE // 1024), 413
    return code, None, 200


class Session:
    def __init__(self, job_id, path, lock):
        self.job_id = job_id
        self.path = path
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
            with open(os.path.join(self.path, name), "rb") as fh:
                chunk = os.pread(fh.fileno(), 65536, self._offsets[name])
        except OSError:
            return ""
        if not chunk:
            return ""
        self._offsets[name] += len(chunk)
        return self._decoders[name].decode(chunk)

    def status(self):
        try:
            with open(os.path.join(self.path, "state.json"),
                      encoding="utf-8") as fh:
                status = json.load(fh)
        except (OSError, ValueError):
            return None
        return status if isinstance(status, dict) else None

    def is_claimed(self):
        return os.path.exists(os.path.join(self.path, ".lock"))

    def worker_alive(self):
        return _lock_held(os.path.join(self.path, "claim"))


def open_session(code):
    if fcntl is None:
        raise RuntimeError("the console needs flock (POSIX only)")

    job_id = new_job_id()
    path = os.path.join(config.SPOOL, job_id)
    os.mkdir(path, 0o755)
    os.mkdir(os.path.join(path, "src"), 0o755)
    with open(os.path.join(path, "src", "main.c"), "w",
              encoding="utf-8") as fh:
        fh.write(code)
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
        json.dump({"kind": KIND}, fh)
    os.replace(tmp, os.path.join(path, "job.json"))
    return Session(job_id, path, lock)


def _lock_held(path):
    # Read-only on purpose: flock needs no write access, and the lock files belong to
    # different users (the API runs as nobody, the worker as root).
    try:
        fd = os.open(path, os.O_RDONLY | os.O_CREAT, 0o644)
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
