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
import re
import shutil
import sys

import content_catalog
import typst_build
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


# THE INSTRUCTOR'S PREVIEW IS A DATE, NOT A SECOND FILTER -- the same idiom as
# `CTESTER_PREVIEW` in runner.py, and for the same reason: `access()` stays the
# ONLY read of a release. Setting the clock to the year 9999 opens everything
# that is dated without touching what is archived, so an archived exercise stays
# invisible to everybody, staff included.
APERCU = dt.datetime(9999, 1, 1, tzinfo=dt.timezone.utc)


# LE MOTIF FERMÉ DES SVG D'ÉNONCÉ. Écrit ici et relu par la ceinture plus bas :
# ce qui sort de `projection()` doit être soit du JSON, soit une page d'énoncé à
# ce nom-là. Le même motif vit dans `app/routers/catalog.py`, qui le fait valoir
# sur ce qui ENTRE -- les deux moitiés d'une seule règle.
ACTIF_RE = re.compile(
    r"\A(?:staff/)?statements/[a-z0-9][a-z0-9-]{0,62}/(?:dark|light)-(?:[1-9]|1[0-6])\.svg\Z")


def projection(model, now=None, renders=None):
    """{relative path: JSON object} -- exactly what the browser can see.

    The catalog carries EVERY exercise, open or not (a lock and a date). The
    detail and the quiz are only written for what is open: `find_exercise`
    is the gate, here as in the API and the worker.

    WHAT IS NOT OPEN YET IS WRITTEN UNDER `staff/`, AND DATES ARE FOR STUDENTS.
    The instructor must be able to see a statement render and submit against
    the real tests before the class does; the API tier does not mount
    `CTESTER_CONTENT`, so if the release does not carry that detail, nobody can
    serve it. The prefix is what an authenticated moderator's request reads
    (`services.catalog.source_publiee`), and nothing else resolves to it --
    which is why this is not `CTESTER_PREVIEW`, a process-wide flag that would
    open the whole term to everyone.

    UNDER `CTESTER_PREVIEW` THIS BRANCH IS DEAD: `now` is already the year 9999,
    so everything is open and `staff/` stays empty. The two never stack.
    """
    renders = renders or {}
    files = {"catalog.json": content_catalog.public_catalogue(model, now)}
    for exercise_id, entry in model["exercises"].items():
        pages = renders.get(exercise_id) or {}
        compte = len(pages.get("dark") or ())
        detail = content_catalog.public_detail(model, exercise_id, now, compte)
        prefixe = ""
        if detail is None:
            detail = content_catalog.public_detail(model, exercise_id, APERCU, compte)
            if detail is None:
                continue  # archived: there is nothing to show anybody
            prefixe = "staff/"
        files["%sexercises/%s.json" % (prefixe, exercise_id)] = detail
        if entry["mode"] == "quiz":
            files["%squiz/%s.json" % (prefixe, exercise_id)] = public_quiz(entry["config"])
        # LES SVG SUIVENT LE DÉTAIL, DONC LE MÊME PRÉFIXE. Un énoncé pas encore
        # ouvert n'a de pages que sous `staff/`, exactement comme son détail :
        # l'enseignant peut vérifier le rendu avant le cours, l'étudiant lit un
        # cadenas et une date. Écrire ce préfixe à un second endroit serait
        # l'endroit où les deux finiraient par diverger.
        for theme, rendu in sorted(pages.items()):
            for numero, octets in enumerate(rendu, 1):
                files["%sstatements/%s/%s-%d.svg"
                      % (prefixe, exercise_id, theme, numero)] = octets
    fuites = sorted({key for value in files.values() for key in _cles(value)}
                    & INTERDIT)
    if fuites:
        raise content_catalog.ContentValidationError(
            ["private key in the public projection: " + ", ".join(fuites)])
    # DEUX CEINTURES DE PLUS, MÊME ESPRIT QUE `INTERDIT`. La première dit que
    # les SOURCES ne sortent pas : un `statement.typ` est du contenu privé, et
    # l'étudiant reçoit ce qui en a été rendu. La seconde dit que tout ce qui
    # n'est pas du JSON est une page d'énoncé et rien d'autre -- un jour où
    # quelqu'un ajoutera un type d'artefact, c'est ici qu'il devra le déclarer.
    for chemin, valeur in sorted(files.items()):
        if chemin.endswith(".typ"):
            raise content_catalog.ContentValidationError(
                ["a Typst source reached the public projection: " + chemin])
        if isinstance(valeur, bytes) and not ACTIF_RE.match(chemin):
            raise content_catalog.ContentValidationError(
                ["unexpected binary artefact in the projection: " + chemin])
    return files


def revision(files):
    """The hash of the published content, i.e. its release name.

    LES SVG ENTRENT DANS LE HACHAGE, ET C'EST CE QUI REND UN RENDU
    ROLLBACKABLE. Un `.tmTheme` corrigé ne change aucun JSON : si seule la part
    JSON était hachée, la révision resterait la même, le répertoire existerait
    déjà, et `publish()` n'écrirait rien -- la correction ne serait jamais
    servie. Les octets sont donc hachés à part, dans l'ordre des chemins, et
    mêlés au même condensé.
    """
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
    """The active publication's directory, or None. Re-read on every call."""
    try:
        with open(os.path.join(dest, POINTER), encoding="utf-8") as fh:
            rev = json.load(fh)["revision"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    path = os.path.join(dest, rev)
    return path if os.path.isdir(path) else None


def _write(path, value):
    """One projection entry: JSON, or the raw bytes of a rendered statement page."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if isinstance(value, bytes):
        with open(path, "wb") as fh:
            fh.write(value)
        return
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(value, fh, ensure_ascii=False)


def publish(model, dest, now=None, keep=3, renders=None):
    """Writes the release, switches the pointer, keeps the last `keep`.

    The order is the invariant: everything is written BEFORE the pointer
    moves, and the pointer moves with a single `os.replace`. An interrupted
    publish leaves an orphaned directory nobody reads.
    """
    files = projection(model, now, renders)
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


def _publie_le(dest, name):
    """When this release was published. THE MANIFEST SAYS SO, the mtime is the
    fallback.

    NOT `getmtime` AS THE PRIMARY SOURCE, and that is a bug already paid for.
    A directory's mtime has the granularity the FILESYSTEM gives it -- on
    Linux that is a kernel tick, so several publications a few milliseconds
    apart share one timestamp. `_elaguer` then sorted on the tuple's SECOND
    element, the revision hash, i.e. on nothing at all: it kept an arbitrary
    release and deleted one it had promised to keep. It passed on Windows
    (100 ns timestamps) and failed on the Dell, which is the worst place for
    a difference like this to live.

    `published_at` is written by `publish()` itself, from
    `datetime.now(timezone.utc)` -- microseconds, and the same everywhere
    because it never touches the filesystem's clock. Two publications cannot
    share it: writing a release takes longer than a microsecond.

    THE FALLBACK IS NOT DECORATION: a release published by an older version
    has a manifest without... no, it has one -- but a half-copied deploy or a
    directory somebody made by hand does not, and it must still be prunable
    rather than immortal.
    """
    chemin = os.path.join(dest, name)
    try:
        with open(os.path.join(chemin, "manifest.json"), encoding="utf-8") as fh:
            return dt.datetime.fromisoformat(json.load(fh)["published_at"]).timestamp()
    except (OSError, ValueError, KeyError, TypeError):
        return os.path.getmtime(chemin)


def _elaguer(dest, garder, keep):
    """Old releases are the rollback: a few of them are kept.

    THE ONES KEPT ARE THE LATEST PUBLISHED, and that has to be true even when
    two publications land in the same clock tick -- see `_publie_le`. The name
    stays in the sort key so the order is TOTAL: two releases that genuinely
    share an instant are still pruned in a reproducible order, rather than in
    whatever order `listdir` happened to return.
    """
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
    # `--no-render` VALIDE SANS COMPILER, et c'est ce que `validate_content.py`
    # fait déjà : le schéma, la collision md/typ, les identifiants. Utile là où
    # il n'y a ni Docker ni binaire typst, et jamais en production -- publier
    # sans rendre écrirait un détail annonçant des pages qui n'existent pas.
    parser.add_argument("--no-render", action="store_true",
                        help="skip Typst rendering (schema only, never in production)")
    args = parser.parse_args(argv)
    try:
        model = content_catalog.discover(args.root)
        renders, compte = ({}, (0, 0)) if args.no_render else typst_build.render_all(model)
        rev = publish(model, args.dest, keep=args.keep, renders=renders)
    except typst_build.TypstError as exc:
        # UNE ERREUR TYPST NE PUBLIE RIEN. Le rendu est fait AVANT la première
        # écriture, donc la release active n'a pas bougé -- exactement ce que
        # `discover()` garantit déjà pour un contenu invalide.
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
