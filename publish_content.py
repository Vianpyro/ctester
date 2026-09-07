#!/usr/bin/env python3
"""Publish v2 content: an allow-listed, dated, reversible projection.

THIS FILE COPIES NOTHING. runner.py's `publish_catalogue()` used to write
files derived from private content into the application's clone; here we
build an in-memory dict from the VALIDATED MODEL (content_catalog), read it
back looking for keys that have no business leaving, then write it into a
directory named after its own hash. A recursive copy, by contrast, publishes
whatever anyone dropped into the folder on a Tuesday evening.

TWO PROPERTIES THAT DO ALL THE REST:

- The revision IS the hash of what is published. Republishing unchanged
  content creates nothing, republishing changed content creates one more
  directory, and the two coexist -- a rollback is a pointer to rewrite, not a
  restore.
- The pointer is a small file replaced with `os.replace`. A symlink would
  have been more elegant, but a Docker mount resolves the link at attach
  time: switching `current` back would only show up on container restart.
  ponytail: JSON pointer re-read on every request, symlink the day the web
  tier no longer reads the parent directory.

Invalid content never replaces the active publication: `discover()` raises
before a single line is written, and the pointer only moves last.
"""

import argparse
import datetime as dt
import hashlib
import json
import os
import shutil
import sys

import content_catalog
from runner import public_quiz

POINTER = "current.json"

# KEYS THAT DO NOT GO OUT, checked ON THE PROJECTION and not on the source.
# public_catalogue / public_detail / public_quiz already rebuild field by
# field; this check is the belt that catches the field added to one of the
# three tomorrow. It checks KEYS: a statement containing the word "note" is
# text, not a leak.
INTERDIT = frozenset((
    "answer", "answers", "expect", "expected", "stdin", "cases", "tolerance",
    "note", "notes", "path", "paths", "seed", "solution", "solutions",
    "allowed_includes", "config",
))


def _cles(value):
    """Every key of a JSON structure, at any depth."""
    if isinstance(value, dict):
        for key, sub in value.items():
            yield key
            for found in _cles(sub):
                yield found
    elif isinstance(value, list):
        for item in value:
            for found in _cles(item):
                yield found


def projection(model, now=None):
    """{relative path: JSON object} -- exactly what the browser can see.

    The catalog carries EVERY exercise, open or not (a lock and a date). The
    detail and the quiz are only written for what is open: `find_exercise`
    is the gate, here as in the API and the worker.
    """
    files = {"catalog.json": content_catalog.public_catalogue(model, now)}
    for exercise_id, entry in model["exercises"].items():
        detail = content_catalog.public_detail(model, exercise_id, now)
        if detail is None:
            continue
        files["exercises/%s.json" % exercise_id] = detail
        if entry["mode"] == "quiz":
            files["quiz/%s.json" % exercise_id] = public_quiz(entry["config"])
    fuites = sorted({key for value in files.values() for key in _cles(value)}
                    & INTERDIT)
    if fuites:
        raise content_catalog.ContentValidationError(
            ["private key in the public projection: " + ", ".join(fuites)])
    return files


def revision(files):
    """The hash of the published content, i.e. its release name."""
    payload = json.dumps(files, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


def current(dest):
    """The active publication's directory, or None. Re-read on every call."""
    try:
        with open(os.path.join(dest, POINTER), encoding="utf-8") as fh:
            rev = json.load(fh)["revision"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    path = os.path.join(dest, rev)
    return path if os.path.isdir(path) else None


def _write(path, value):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(value, fh, ensure_ascii=False)


def publish(model, dest, now=None, keep=3):
    """Writes the release, switches the pointer, keeps the last `keep`.

    The order is the invariant: everything is written BEFORE the pointer
    moves, and the pointer moves with a single `os.replace`. An interrupted
    publish leaves an orphaned directory nobody reads.
    """
    files = projection(model, now)
    rev = revision(files)
    release = os.path.join(dest, rev)
    if not os.path.isdir(release):
        temporaire = release + ".tmp"
        shutil.rmtree(temporaire, ignore_errors=True)
        for relatif, value in files.items():
            _write(os.path.join(temporaire, relatif.replace("/", os.sep)), value)
        # The manifest is OUTSIDE the hash: its date would change identical
        # content's revision, and two publishes of the same content must
        # carry the same name so republishing costs nothing.
        _write(os.path.join(temporaire, "manifest.json"), {
            "schema_version": content_catalog.SCHEMA_VERSION, "revision": rev,
            "published_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "exercises": len(model["exercises"]),
            "collections": len(model["collections"]),
            "assignments": len(model.get("assignments", {}))})
        os.replace(temporaire, release)
    pointeur = os.path.join(dest, POINTER)
    _write(pointeur + ".tmp", {"revision": rev,
                               "published_at": dt.datetime.now(dt.timezone.utc).isoformat()})
    os.replace(pointeur + ".tmp", pointeur)
    _elaguer(dest, rev, keep)
    return rev


def _elaguer(dest, garder, keep):
    """Old releases are the rollback: a few of them are kept."""
    releases = [(os.path.getmtime(os.path.join(dest, name)), name)
                for name in os.listdir(dest)
                if name != garder and os.path.isdir(os.path.join(dest, name))]
    for _, name in sorted(releases, reverse=True)[max(keep - 1, 0):]:
        shutil.rmtree(os.path.join(dest, name), ignore_errors=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description="publish ctester v2 content")
    parser.add_argument("root", help="root containing catalog.json and exercises/")
    parser.add_argument("dest", help="directory for releases (published/)")
    parser.add_argument("--keep", type=int, default=3, help="releases kept")
    args = parser.parse_args(argv)
    try:
        model = content_catalog.discover(args.root)
        rev = publish(model, args.dest, keep=args.keep)
    except content_catalog.ContentValidationError as exc:
        print("publish refused, the active release is untouched:", file=sys.stderr)
        for error in exc.errors:
            print("- " + error, file=sys.stderr)
        return 1
    print("published: revision %s (%d exercise(s), %d collection(s))"
          % (rev, len(model["exercises"]), len(model["collections"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
