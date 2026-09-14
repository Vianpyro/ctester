import headers
import security
import state
from deps import Sub, throttle_write
from fastapi import APIRouter, Query, Request
from schemas import DraftIn, PreferencesIn
from services.catalog import find_exercise, validate_files

router = APIRouter(tags=["account"])


@router.get("/etats")
def get_statuses(sub: Sub):
    values = state.read_states(sub)
    if values is None:
        return headers.error(503, "la base ne répond pas")
    return {"states": values, "moderator": security.is_moderator(sub)}


@router.get("/pratique")
def get_practice(sub: Sub):
    summary = state.read_practice_summary(sub)
    if summary is None:
        return headers.error(503, "la base ne répond pas")
    return {"practice": summary}


@router.get("/brouillon")
def get_draft(sub: Sub, ex: str = Query("")):
    if find_exercise(ex, security.is_moderator(sub)) is None:
        return headers.error(400, "TP inconnu")
    return {"sources": state.read_resume(sub, ex)}


@router.put("/brouillon")
def put_draft(sub: Sub, body: DraftIn, request: Request):
    entry = find_exercise(body.exercise_id, security.is_moderator(sub))
    if entry is None:
        return headers.error(400, "TP inconnu")
    files, message, code = validate_files(entry, body.files)
    if message:
        return headers.error(code, message)
    throttle_write(request)
    if not state.write_draft(sub, entry["id"], files):
        return headers.error(503, "la base ne répond pas")
    return {"ok": True}


@router.get("/preferences")
def get_preferences(sub: Sub):
    theme = state.read_theme(sub)
    if theme is None:
        return headers.error(503, "la base ne répond pas")
    return {"theme": theme}


@router.put("/preferences")
def put_preferences(sub: Sub, body: PreferencesIn, request: Request):
    if body.theme not in state.THEMES:
        return headers.error(400, "thème inconnu")
    throttle_write(request)
    if not state.write_theme(sub, body.theme):
        return headers.error(503, "la base ne répond pas")
    return {"ok": True}


@router.delete("/moi")
def delete_account(sub: Sub):
    if not state.forget(sub):
        return headers.error(503, "la base ne répond pas")
    return {"ok": True}
