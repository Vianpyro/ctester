import headers
import security
import state
from deps import Sub, throttle_write
from fastapi import APIRouter, Query, Request
from schemas import DraftIn, PreferencesIn
from services.catalog import find_exercise, validate_files

router = APIRouter(tags=["account"])


@router.get("/states")
def get_statuses(sub: Sub):
    values = state.read_states(sub)
    if values is None:
        return headers.error(503, "db_down")
    return {"states": values, "moderator": security.is_moderator(sub)}


@router.get("/practice")
def get_practice(sub: Sub):
    summary = state.read_practice_summary(sub)
    if summary is None:
        return headers.error(503, "db_down")
    return {"practice": summary}


@router.get("/draft")
def get_draft(sub: Sub, ex: str = Query("")):
    if find_exercise(ex, security.is_moderator(sub)) is None:
        return headers.error(400, "unknown_exercise")
    return {"sources": state.read_resume(sub, ex)}


@router.put("/draft")
def put_draft(sub: Sub, body: DraftIn, request: Request):
    entry = find_exercise(body.exercise_id, security.is_moderator(sub))
    if entry is None:
        return headers.error(400, "unknown_exercise")
    files, message, code = validate_files(entry, body.files)
    if message:
        return headers.error(code, message)
    throttle_write(request)
    if not state.write_draft(sub, entry["id"], files):
        return headers.error(503, "db_down")
    return {"ok": True}


@router.get("/preferences")
def get_preferences(sub: Sub):
    prefs = state.read_preferences(sub)
    if prefs is None:
        return headers.error(503, "db_down")
    return prefs


@router.put("/preferences")
def put_preferences(sub: Sub, body: PreferencesIn, request: Request):
    if not body.theme and not body.lang:
        return headers.error(400, "nothing_to_save")
    if body.theme and body.theme not in state.THEMES:
        return headers.error(400, "unknown_theme")
    if body.lang and not state.valid_lang(body.lang):
        return headers.error(400, "unknown_language")
    throttle_write(request)
    if not state.write_preferences(sub, body.theme, body.lang):
        return headers.error(503, "db_down")
    return {"ok": True}


@router.delete("/account")
def delete_account(sub: Sub):
    if not state.forget(sub):
        return headers.error(503, "db_down")
    return {"ok": True}
