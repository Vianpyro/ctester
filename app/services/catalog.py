import json
import os
import re

import config
from services.source import canonicalize

REVISION_RE = re.compile(r"\A[0-9a-f]{8,64}\Z")


def release_dir():
    if not config.PUBLISHED:
        return None
    try:
        with open(os.path.join(config.PUBLISHED, "current.json"), encoding="utf-8") as fh:
            revision = json.load(fh)["revision"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if not isinstance(revision, str) or not REVISION_RE.match(revision):
        return None
    path = os.path.join(config.PUBLISHED, revision)
    return path if os.path.isdir(path) else None


def load_catalog():
    release = release_dir()
    if release is None:
        return None
    try:
        with open(os.path.join(release, "catalog.json"), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


PAGE_RE = re.compile(r"\A(?:(?:dark|light)-(?:[1-9]|1[0-6])\.svg|statement\.html)\Z")


def published_source(entry, what, name=None):
    release = release_dir()
    if release is None:
        return None, None
    if what == "statement":
        if not isinstance(name, str) or not PAGE_RE.match(name):
            return None, None
        directory = os.path.join("statements", entry["id"])
        if entry.get("access") != "available":
            directory = os.path.join("staff", directory)
        return release, os.path.join(directory, name)
    directory = "exercises" if what == "detail" else "quiz"
    if entry.get("access") != "available":
        directory = os.path.join("staff", directory)
    return release, os.path.join(directory, entry["id"] + ".json")


def _published():
    return [entry for entry in (load_catalog() or {}).get("exercises") or ()
            if isinstance(entry, dict) and isinstance(entry.get("id"), str)]


def open_exercises():
    return [entry for entry in _published() if entry.get("access") == "available"]


def find_exercise(exercise_id, preview=False):
    """The gate for every exercise lookup. Unopened exercises need preview=True."""
    for entry in (_published() if preview else open_exercises()):
        if entry["id"] == exercise_id:
            return entry
    return None


def validate_files(entry, sent):
    if not isinstance(sent, dict):
        return None, "fichiers manquants", 400
    declared = [f["name"] for f in entry.get("files") or []] or ["submission.c"]
    unknown = sorted(k for k in sent if k not in declared)
    if unknown:
        return None, "fichier inattendu : " + ", ".join(unknown[:3]), 400
    # Canonicalized before measuring, so the bound applies to the bytes actually stored.
    files = {n: canonicalize(str(sent.get(n, ""))) for n in declared}
    if len(json.dumps(files).encode()) > config.MAX_CODE:
        return None, f"soumission > {config.MAX_CODE // 1024} Ko", 413
    return files, None, 200
