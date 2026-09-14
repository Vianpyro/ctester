#!/usr/bin/env python3

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import sys

import content_catalog
import typst_build
from runner import public_quiz

POINTER = "current.json"

# Checked on the projection itself, so a field added later cannot leak an answer key.
INTERDIT = frozenset((
    "answer", "answers", "expect", "expected", "stdin", "cases", "tolerance",
    "note", "notes", "path", "paths", "seed", "solution", "solutions",
    "allowed_includes", "config",
))


def _cles(value):
    if isinstance(value, dict):
        for key, sub in value.items():
            yield key
            for found in _cles(sub):
                yield found
    elif isinstance(value, list):
        for item in value:
            for found in _cles(item):
                yield found


# Preview is a date rather than a second filter, so access() stays the only rule.
APERCU = dt.datetime(9999, 1, 1, tzinfo=dt.timezone.utc)


ACTIF_RE = re.compile(
    r"\A(?:staff/)?statements/[a-z0-9][a-z0-9-]{0,62}/"
    r"(?:(?:dark|light)-(?:[1-9]|1[0-6])\.svg|statement\.html)\Z")


def projection(model, now=None, renders=None):
    renders = renders or {}
    files = {"catalog.json": content_catalog.public_catalogue(model, now)}
    for exercise_id, entry in model["exercises"].items():
        pages = renders.get(exercise_id) or {}
        compte = len(pages.get("dark") or ())
        html = pages.get("html")
        detail = content_catalog.public_detail(model, exercise_id, now, compte, bool(html))
        prefixe = ""
        if detail is None:
            detail = content_catalog.public_detail(model, exercise_id, APERCU, compte,
                                                   bool(html))
            if detail is None:
                continue
            prefixe = "staff/"
        files["%sexercises/%s.json" % (prefixe, exercise_id)] = detail
        if entry["mode"] == "quiz":
            files["%squiz/%s.json" % (prefixe, exercise_id)] = public_quiz(entry["config"])
        if html:
            files["%sstatements/%s/statement.html" % (prefixe, exercise_id)] = html
        for theme in typst_build.THEMES:
            for numero, octets in enumerate(pages.get(theme) or (), 1):
                files["%sstatements/%s/%s-%d.svg"
                      % (prefixe, exercise_id, theme, numero)] = octets
    fuites = sorted({key for value in files.values() for key in _cles(value)}
                    & INTERDIT)
    if fuites:
        raise content_catalog.ContentValidationError(
            ["private key in the public projection: " + ", ".join(fuites)])
    for chemin, valeur in sorted(files.items()):
        if chemin.endswith(".typ"):
            raise content_catalog.ContentValidationError(
                ["a Typst source reached the public projection: " + chemin])
        if isinstance(valeur, bytes) and not ACTIF_RE.match(chemin):
            raise content_catalog.ContentValidationError(
                ["unexpected binary artefact in the projection: " + chemin])
    return files


def revision(files):
    # Rendered SVGs are hashed too: a changed rendering must produce a new release.
    json_part = {chemin: valeur for chemin, valeur in files.items()
                 if not isinstance(valeur, bytes)}
    h = hashlib.sha256()
    h.update(json.dumps(json_part, sort_keys=True, ensure_ascii=False).encode("utf-8"))
    for chemin in sorted(files):
        valeur = files[chemin]
        if isinstance(valeur, bytes):
            h.update(b"\0")
            h.update(chemin.encode("utf-8"))
            h.update(b"\0")
            h.update(hashlib.sha256(valeur).digest())
    return h.hexdigest()[:16]


def current(dest):
    try:
        with open(os.path.join(dest, POINTER), encoding="utf-8") as fh:
            rev = json.load(fh)["revision"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    path = os.path.join(dest, rev)
    return path if os.path.isdir(path) else None


def _write(path, value):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if isinstance(value, bytes):
        with open(path, "wb") as fh:
            fh.write(value)
        return
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(value, fh, ensure_ascii=False)


def publish(model, dest, now=None, keep=3, renders=None):
    # The pointer moves last. It is a file, not a symlink, because Docker resolves
    # symlinks at mount time and a switch would only show after a restart.
    files = projection(model, now, renders)
    rev = revision(files)
    release = os.path.join(dest, rev)
    if not os.path.isdir(release):
        temporaire = release + ".tmp"
        shutil.rmtree(temporaire, ignore_errors=True)
        for relatif, value in files.items():
            _write(os.path.join(temporaire, relatif.replace("/", os.sep)), value)
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


def _publie_le(dest, name):
    # From the manifest: on Linux, releases published in quick succession share a directory mtime.
    chemin = os.path.join(dest, name)
    try:
        with open(os.path.join(chemin, "manifest.json"), encoding="utf-8") as fh:
            return dt.datetime.fromisoformat(json.load(fh)["published_at"]).timestamp()
    except (OSError, ValueError, KeyError, TypeError):
        return os.path.getmtime(chemin)


def _elaguer(dest, garder, keep):
    releases = [(_publie_le(dest, name), name)
                for name in os.listdir(dest)
                if name != garder and os.path.isdir(os.path.join(dest, name))]
    for _, name in sorted(releases, reverse=True)[max(keep - 1, 0):]:
        shutil.rmtree(os.path.join(dest, name), ignore_errors=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description="publish ctester v2 content")
    parser.add_argument("root", help="root containing catalog.json and exercises/")
    parser.add_argument("dest", help="directory for releases (published/)")
    parser.add_argument("--keep", type=int, default=3, help="releases kept")
    parser.add_argument("--no-render", action="store_true",
                        help="skip Typst rendering (schema only, never in production)")
    args = parser.parse_args(argv)
    try:
        model = content_catalog.discover(args.root)
        renders, compte = ({}, (0, 0)) if args.no_render else typst_build.render_all(model, args.dest)
        rev = publish(model, args.dest, keep=args.keep, renders=renders)
    except typst_build.TypstError as exc:
        print("publish refused, the active release is untouched:", file=sys.stderr)
        print("- " + str(exc), file=sys.stderr)
        return 1
    except content_catalog.ContentValidationError as exc:
        print("publish refused, the active release is untouched:", file=sys.stderr)
        for error in exc.errors:
            print("- " + error, file=sys.stderr)
        return 1
    print("published: revision %s (%d exercise(s), %d collection(s), "
          "%d Typst statement(s), %d from cache)"
          % (rev, len(model["exercises"]), len(model["collections"]),
             compte[0], compte[1]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
