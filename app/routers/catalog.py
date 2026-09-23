import os

import headers
from deps import Preview
from fastapi import APIRouter, Request
from services.catalog import find_exercise, release_dir, published_source

router = APIRouter(tags=["catalog"])


@router.get("/catalog.json")
def catalog(request: Request):
    release = release_dir()
    if release is None:
        return headers.error(404, "catalogue absent")
    return headers.file_from_disk(request, release, "catalog.json",
                                  "application/json; charset=utf-8")


@router.get("/exercise/{exercise_id}.json")
def detail(exercise_id: str, request: Request, preview: Preview):
    entry = find_exercise(exercise_id, preview)
    if entry is None:
        return headers.error(404, "unknown")
    base, name = published_source(entry, "detail")
    if base is None:
        return headers.error(404, "unknown")
    return headers.file_from_disk(request, base, name,
                                  "application/json; charset=utf-8",
                                  private=entry.get("access") != "available")


@router.get("/quiz/{exercise_id}.json")
def quiz(exercise_id: str, request: Request, preview: Preview):
    entry = find_exercise(exercise_id, preview)
    if entry is None or entry.get("mode") != "quiz":
        return headers.error(404, "not_a_quiz")
    base, name = published_source(entry, "quiz")
    if base is None:
        return headers.error(404, "not_a_quiz")
    return headers.file_from_disk(request, base, name,
                                  "application/json; charset=utf-8",
                                  private=entry.get("access") != "available")


@router.get("/statement/{exercise_id}/{name}")
def statement(exercise_id: str, name: str, request: Request, preview: Preview):
    entry = find_exercise(exercise_id, preview)
    if entry is None:
        return headers.error(404, "unknown")
    base, path = published_source(entry, "statement", name)
    if base is None:
        return headers.error(404, "unknown")
    if not os.path.isfile(os.path.join(base, path)):
        return headers.error(404, "unknown")
    ctype = ("text/plain; charset=utf-8" if name.endswith(".html")
             else "image/svg+xml")
    return headers.file_from_disk(request, base, path, ctype,
                                  private=entry.get("access") != "available")
