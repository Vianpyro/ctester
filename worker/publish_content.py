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

POINTER = "current.json"


def _published_options(question):
    """The pool a widget shows. Sorted wherever the author's own order would be the key."""
    kind = str(question.get("type", "int"))
    answer = question.get("answer")
    if kind == "bool":
        # Synthesised, never read from the file: the key has no published image at all.
        return ["Vrai", "Faux"]
    if kind == "order":
        # Every permutation of the same items projects to the same list, so the published
        # release carries no information about the correct order.
        return sorted(str(item) for item in answer or [])
    if kind == "match":
        pool = {str(item) for item in question.get("options") or []}
        if isinstance(answer, dict):
            pool |= {str(partner) for partner in answer.values()}
        # Sorted, so no habit of the author can correlate the two columns.
        return sorted(pool)
    return [str(option) for option in question.get("options") or []]


def _prompts(question):
    """The left column of a matching question, in the order the author wrote it: a
    prompt's position says nothing about its partner."""
    answer = question.get("answer")
    if str(question.get("type", "int")) != "match" or not isinstance(answer, dict):
        return []
    return [str(prompt) for prompt in answer]


def _gaps(question):
    """One entry per gap, in template order. Empty means the gap is typed, not chosen."""
    answer = question.get("answer")
    if str(question.get("type", "int")) != "cloze" or not isinstance(answer, list):
        return []
    return [sorted({str(choice)
                    for choice in (gap.get("choices") if isinstance(gap, dict) else None) or []})
            for gap in answer]


def public_quiz(quiz):
    """Rebuilt field by field, so an answer key can never leak into the release. Every
    question carries the same ten keys whatever its type: the shape must say nothing."""
    return {
        "label": quiz.get("label", ""),
        "questions": [
            {
                "id": str(q.get("id", "")),
                "group": str(q.get("group", "")),
                "label": str(q.get("label", "")),
                "row": str(q.get("row", "")),
                "col": str(q.get("col", "")),
                "type": str(q.get("type", "int")),
                "options": _published_options(q),
                "prompts": _prompts(q),
                "template": str(q.get("template", "")),
                "gaps": _gaps(q),
            }
            for q in quiz.get("questions", [])
        ],
    }

# Checked on the projection itself, so a field added later cannot leak an answer key.
FORBIDDEN = frozenset((
    "answer", "answers", "accept", "margin", "expect", "expected", "stdin", "cases",
    "tolerance", "note", "notes", "path", "paths", "seed", "solution", "solutions",
    "allowed_includes", "config",
))


def _keys(value):
    if isinstance(value, dict):
        for key, sub in value.items():
            yield key
            for found in _keys(sub):
                yield found
    elif isinstance(value, list):
        for item in value:
            for found in _keys(item):
                yield found


# Preview is a date rather than a second filter, so access() stays the only rule.
PREVIEW = dt.datetime(9999, 1, 1, tzinfo=dt.timezone.utc)


ACTIVE_RE = re.compile(
    r"\A(?:staff/)?statements/[a-z0-9][a-z0-9-]{0,62}/"
    r"(?:(?:dark|light)-(?:[1-9]|1[0-6])\.svg|statement\.html)\Z")


def projection(model, now=None, renders=None):
    renders = renders or {}
    files = {"catalog.json": content_catalog.public_catalogue(model, now)}
    for exercise_id, entry in model["exercises"].items():
        pages = renders.get(exercise_id) or {}
        account = len(pages.get("dark") or ())
        html = pages.get("html")
        detail = content_catalog.public_detail(model, exercise_id, now, account, bool(html))
        prefix = ""
        if detail is None:
            detail = content_catalog.public_detail(model, exercise_id, PREVIEW, account,
                                                   bool(html))
            if detail is None:
                continue
            prefix = "staff/"
        files["%sexercises/%s.json" % (prefix, exercise_id)] = detail
        if entry["mode"] == "quiz":
            files["%squiz/%s.json" % (prefix, exercise_id)] = public_quiz(entry["config"])
        if html:
            files["%sstatements/%s/statement.html" % (prefix, exercise_id)] = html
        for theme in typst_build.THEMES:
            for number, data in enumerate(pages.get(theme) or (), 1):
                files["%sstatements/%s/%s-%d.svg"
                      % (prefix, exercise_id, theme, number)] = data
    leaks = sorted({key for value in files.values() for key in _keys(value)}
                    & FORBIDDEN)
    if leaks:
        raise content_catalog.ContentValidationError(
            ["private key in the public projection: " + ", ".join(leaks)])
    for path, content in sorted(files.items()):
        if path.endswith(".typ"):
            raise content_catalog.ContentValidationError(
                ["a Typst source reached the public projection: " + path])
        if isinstance(content, bytes) and not ACTIVE_RE.match(path):
            raise content_catalog.ContentValidationError(
                ["unexpected binary artefact in the projection: " + path])
    return files


def revision(files):
    # Rendered SVGs are hashed too: a changed rendering must produce a new release.
    json_part = {path: value for path, value in files.items()
                 if not isinstance(value, bytes)}
    h = hashlib.sha256()
    h.update(json.dumps(json_part, sort_keys=True, ensure_ascii=False).encode("utf-8"))
    for path in sorted(files):
        value = files[path]
        if isinstance(value, bytes):
            h.update(b"\0")
            h.update(path.encode("utf-8"))
            h.update(b"\0")
            h.update(hashlib.sha256(value).digest())
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


def _releases(value):
    if isinstance(value, dict):
        if isinstance(value.get("release"), dict):
            yield value["release"]
        for sub in value.values():
            yield from _releases(sub)
    elif isinstance(value, list):
        for item in value:
            yield from _releases(item)


def next_release(model, now=None):
    """The earliest opening still ahead: content.sh republishes once it has passed."""
    now = now or dt.datetime.now(dt.timezone.utc)
    moments = [moment for release in _releases(model)
               if release.get("state") == "scheduled"
               for moment in [content_catalog._iso_datetime(release.get("available_from"))]
               if moment is not None and moment > now]
    return min(moments).isoformat() if moments else None


def publish(model, dest, now=None, keep=3, renders=None):
    # The pointer moves last. It is a file, not a symlink, because Docker resolves
    # symlinks at mount time and a switch would only show after a restart.
    files = projection(model, now, renders)
    rev = revision(files)
    release = os.path.join(dest, rev)
    if not os.path.isdir(release):
        temporary = release + ".tmp"
        shutil.rmtree(temporary, ignore_errors=True)
        for relative, value in files.items():
            _write(os.path.join(temporary, relative.replace("/", os.sep)), value)
        _write(os.path.join(temporary, "manifest.json"), {
            "schema_version": content_catalog.SCHEMA_VERSION, "revision": rev,
            "published_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "exercises": len(model["exercises"]),
            "collections": len(model["collections"]),
            "assignments": len(model.get("assignments", {}))})
        os.replace(temporary, release)
    pointer = os.path.join(dest, POINTER)
    _write(pointer + ".tmp", {"revision": rev,
                               "published_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                               "next_release": next_release(model, now)})
    os.replace(pointer + ".tmp", pointer)
    _prune(dest, rev, keep)
    return rev


def _published_at(dest, name):
    # From the manifest: on Linux, releases published in quick succession share a directory mtime.
    path = os.path.join(dest, name)
    try:
        with open(os.path.join(path, "manifest.json"), encoding="utf-8") as fh:
            return dt.datetime.fromisoformat(json.load(fh)["published_at"]).timestamp()
    except (OSError, ValueError, KeyError, TypeError):
        return os.path.getmtime(path)


def _prune(dest, live_revision, keep):
    releases = [(_published_at(dest, name), name)
                for name in os.listdir(dest)
                if name != live_revision and os.path.isdir(os.path.join(dest, name))]
    for _, name in sorted(releases, reverse=True)[max(keep - 1, 0):]:
        shutil.rmtree(os.path.join(dest, name), ignore_errors=True)


def publish_catalogue(content, published, preview=False):
    """What ctester-content.timer runs; the judge no longer publishes anything."""
    if preview:
        print("ctester: PREVIEW ACTIVE -- exercises not yet open are being published",
              file=sys.stderr, flush=True)
    if not (content and published):
        raise RuntimeError(
            "CTESTER_CONTENT and CTESTER_PUBLISHED are required to publish")
    model = content_catalog.discover(content_catalog.content_roots(content))
    renders, (total, cached) = typst_build.render_all(model, published)
    if total:
        print("ctester: %d Typst statement(s) rendered, %d of them from the cache"
              % (total, cached), file=sys.stderr, flush=True)
    publish(model, published, now=PREVIEW if preview else None, renders=renders)
    return list(model["exercises"].values())


def main(argv=None):
    parser = argparse.ArgumentParser(description="publish ctester v2 content")
    parser.add_argument("root", nargs="+",
                        help="root(s) containing catalog.json and exercises/")
    parser.add_argument("dest", help="directory for releases (published/)")
    parser.add_argument("--keep", type=int, default=3, help="releases kept")
    parser.add_argument("--no-render", action="store_true",
                        help="skip Typst rendering (schema only, never in production)")
    args = parser.parse_args(argv)
    try:
        model = content_catalog.discover(args.root)
        renders, account = ({}, (0, 0)) if args.no_render else typst_build.render_all(model, args.dest)
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
             account[0], account[1]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
