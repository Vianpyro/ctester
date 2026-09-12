"""The public catalog: the list of exercises, a statement, a quiz.

THE CATALOG IS ANONYMOUS, and that is ctester's core: a student pastes their
code and submits with no account. The two others read a token for ONE decision
and only that one -- whether the caller is a moderator, who may open an exercise
that is not yet open (dates are for students; the instructor checks the
statement and the verdict before class). With no token, or a student's token,
these routes answer exactly what they always answered.

NO REFERENCE SOLUTION EVER PASSES THROUGH HERE. The served release has already
been rebuilt field by field by `publish_content.py`, which reads its own
projection back and refuses to publish if a private key shows up in it -- and
the runbook replays a `grep` after every deploy.
"""

import os

import headers
from deps import Apercu
from fastapi import APIRouter, Request
from services.catalog import find_exercise, release_dir, source_publiee

router = APIRouter(tags=["catalogue"])


@router.get("/catalog.json")
def catalog(request: Request):
    """The catalog: collections, exercises, access, locks and dates.

    RE-READ ON EVERY CALL, not cached at startup: publishing an exercise is
    then `--tags tests` and nothing else. A cached value would mean recreating
    the container to add one line to a menu, and that is the kind of step one
    forgets the evening a new exercise gets added.
    """
    release = release_dir()
    if release is None:
        return headers.erreur(404, "catalogue absent")
    return headers.fichier_du_disque(request, release, "catalog.json",
                                     "application/json; charset=utf-8")


@router.get("/tp/{exercise_id}.json")
def detail(exercise_id: str, request: Request, apercu: Apercu):
    """An exercise's statement and templates.

    `find_exercise` is the ONLY gate: it refuses anything that is not an open
    catalog exercise, so `/tp/../catalog.json` is not a path to traverse but
    an id that does not exist. For a moderator it also opens on what is not
    yet published to students -- which is a body that must never be kept by a
    cache, hence `prive`.

    ponytail: the URL keeps its historical `/tp/`. It lives in students'
    caches and costs nothing; renaming it will happen alongside
    `/exercises/<id>`, when the page moves to deep links `/exercise/<id>`.
    """
    entry = find_exercise(exercise_id, apercu)
    if entry is None:
        return headers.erreur(404, "inconnu")
    base, nom = source_publiee(entry, "detail")
    if base is None:
        return headers.erreur(404, "inconnu")
    return headers.fichier_du_disque(request, base, nom,
                                     "application/json; charset=utf-8",
                                     prive=entry.get("access") != "available")


@router.get("/quiz/{exercise_id}.json")
def quiz(exercise_id: str, request: Request, apercu: Apercu):
    """A quiz's questions, exactly as the worker published them.

    The path is rebuilt from the catalog, never concatenated from the URL.
    The mode is checked in addition to existence: a code exercise does not
    expose a quiz file. Same moderator door and same `no-store` as `detail`.
    """
    entry = find_exercise(exercise_id, apercu)
    if entry is None or entry.get("mode") != "quiz":
        return headers.erreur(404, "pas un quiz")
    base, nom = source_publiee(entry, "quiz")
    if base is None:
        return headers.erreur(404, "pas un quiz")
    return headers.fichier_du_disque(request, base, nom,
                                     "application/json; charset=utf-8",
                                     prive=entry.get("access") != "available")


@router.get("/statement/{exercise_id}/{nom}")
def statement(exercise_id: str, nom: str, request: Request, apercu: Apercu):
    """One page of a Typst statement, rendered to SVG at publish time.

    NOTHING IS COMPILED HERE, AND NOTHING EVER WILL BE. This container does not
    mount `CTESTER_CONTENT`, has no typst and no Docker socket; the pages were
    written by the worker's publish step (`typst_build.py`) into the release
    this process reads. A statement is a file, exactly like a quiz.

    THE SAME GATE AND THE SAME LOCK AS `/tp/`. `find_exercise` refuses anything
    that is not an open catalog exercise, `source_publiee` refuses a name that
    is not a page, and a not-yet-open exercise only exists under `staff/` -- so
    a moderator sees their preview and a student gets the 404 they always got.

    `prive` FOR A STAFF PAGE, for the reason `fichier_du_disque` spells out: an
    ETag plus `no-cache` tells Cloudflare to keep the body and revalidate it,
    and a student's request could revalidate into a kept staff statement.

    ponytail: the URL carries the theme because the SVG is painted once, at
    build time, and cannot follow `prefers-color-scheme` on its own. The day
    statements are served from the page's own origin, this becomes two files
    next to each other and the route goes away.
    """
    entry = find_exercise(exercise_id, apercu)
    if entry is None:
        return headers.erreur(404, "inconnu")
    base, chemin = source_publiee(entry, "statement", nom)
    if base is None:
        return headers.erreur(404, "inconnu")
    # L'EXISTENCE EST CONTRÔLÉE ICI, pas déduite du détail. Le motif accepte
    # seize pages ; cet énoncé-là en a deux, et la troisième doit répondre 404
    # plutôt que « fichier manquant », qui est un 500.
    if not os.path.isfile(os.path.join(base, chemin)):
        return headers.erreur(404, "inconnu")
    return headers.fichier_du_disque(request, base, chemin, "image/svg+xml",
                                     prive=entry.get("access") != "available")
