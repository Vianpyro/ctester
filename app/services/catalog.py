"""The exercise catalog, and the file allow-list.

`find_exercise()` IS THE ONLY GATE TO AN EXERCISE. The mode, the name of the
file dropped into the spool, the path of a served quiz: everything starts
here. An exercise absent from the published catalog does not exist, whatever
sits on disk -- and an exercise not yet open is not "absent" but "closed",
which is the same answer here and a dated lock in the menu.

The catalog itself is a RELEASE written by the worker (`publish_content.py`,
called by `publish_catalogue()` in `runner.py`), which rebuilds field by field
what comes out. This module only reads it.
"""

import json
import os
import re

import config

# A release's name IS the hash of its content. Validated before being joined
# into a path: this file is written by the worker, but nothing that becomes a
# path is read without being checked.
REVISION_RE = re.compile(r"\A[0-9a-f]{8,64}\Z")


def release_dir():
    """The active release's directory, or None (nothing published).

    RE-READ ON EVERY CALL, like the catalog itself: publishing or rolling back
    is a pointer to rewrite, not a container to recreate.
    """
    if not config.PUBLISHED:
        return None
    try:
        with open(os.path.join(config.PUBLISHED, "current.json"), encoding="utf-8") as fh:
            revision = json.load(fh)["revision"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if not isinstance(revision, str) or not REVISION_RE.match(revision):
        return None
    chemin = os.path.join(config.PUBLISHED, revision)
    return chemin if os.path.isdir(chemin) else None


def load_catalog():
    """The published catalog -- collections, access, exercises. None if nothing is published."""
    release = release_dir()
    if release is None:
        return None
    try:
        with open(os.path.join(release, "catalog.json"), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def source_publiee(entry, quoi):
    """(base, name) of the published file for this exercise, or (None, None).

    The name is REBUILT from the catalog id, never received: there is
    therefore no path to traverse. `None` when the pointer disappeared
    between resolution and reading -- a rollback mid-request is a 404, not a
    stack trace.
    """
    release = release_dir()
    if release is None:
        return None, None
    dossier = "exercises" if quoi == "detail" else "quiz"
    return release, os.path.join(dossier, entry["id"] + ".json")


def exercices_ouverts():
    """The OPEN exercises of the published catalog, in publication order.

    Progression only counts what is open: a locked exercise must neither
    inflate a denominator nor be recommended the day before it opens. This is
    the same list `find_exercise` queries one entry at a time -- a single
    definition of "published and open".
    """
    return [entry for entry in (load_catalog() or {}).get("exercises") or ()
            if isinstance(entry, dict) and entry.get("access") == "available"
            and isinstance(entry.get("id"), str)]


def find_exercise(exercise_id):
    """This OPEN exercise's catalog entry, or None. The only gate.

    Everything that follows -- the mode, the file name written into the
    spool, the path of a served quiz -- starts here. A locked exercise does
    appear in the catalog (with its lock and its date), but does not resolve:
    a deep link shared early does not bypass anything, it just does not
    resolve.
    """
    for entry in exercices_ouverts():
        if entry["id"] == exercise_id:
            return entry
    return None


def validate_files(entry, sent):
    """(files, message, status) -- THE SAME WHITELIST for a submission and a draft.

    File names come from the catalogue, never from the request. From lab 5 on, a
    submission is a module whose names the assignment imposes (calendrier.h,
    calendrier.c): a name that is not on the list is refused rather than dropped
    silently -- a student must know their file was not taken.

    Emptiness is NOT checked here: an empty submission is an error, an emptied
    draft is a legitimate thing to store. The caller decides.
    """
    if not isinstance(sent, dict):
        return None, "fichiers manquants", 400
    declared = [f["name"] for f in entry.get("files") or []] or ["submission.c"]
    unknown = sorted(k for k in sent if k not in declared)
    if unknown:
        return None, "fichier inattendu : " + ", ".join(unknown[:3]), 400
    files = {n: str(sent.get(n, "")) for n in declared}
    if len(json.dumps(files).encode()) > config.MAX_CODE:
        return None, f"soumission > {config.MAX_CODE // 1024} Ko", 413
    return files, None, 200
