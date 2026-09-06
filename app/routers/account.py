"""An account's state: exercises, drafts, preferences, erasure.

ALL THESE ROUTES GO THROUGH `Sub`, AND NONE TAKES AN ID FROM THE REQUEST.
`security.current_user()` is the only source of `account`: that is what keeps
one student from writing into another's state.

A MUTE DATABASE ANSWERS 503, NEVER 200. The page only shows "saved" on a true
response: a 200 on a write that never happened would make someone believe
their work is safe.
"""

import state
import headers
from deps import Sub, freiner_ecriture
from fastapi import APIRouter, Query, Request
from schemas import BrouillonIn, PreferencesIn
from services.catalog import find_exercise, validate_files

router = APIRouter(tags=["compte"])


@router.get("/etats")
def etats(sub: Sub):
    """The exercises this account has attempted or solved."""
    valeurs = state.read_states(sub)
    if valeurs is None:
        return headers.erreur(503, "la base ne répond pas")
    return {"etats": valeurs}


@router.get("/pratique")
def pratique(sub: Sub):
    """This account's summary of free practice attempts."""
    resume = state.read_practice_summary(sub)
    if resume is None:
        return headers.erreur(503, "la base ne répond pas")
    return {"pratique": resume}


@router.get("/brouillon")
def lire_brouillon(sub: Sub, ex: str = Query("")):
    """The code in progress for ONE exercise.

    A MISSING DRAFT IS NOT AN ERROR: it is a student opening an exercise for
    the first time. `sources: null` says so plainly.
    """
    if find_exercise(ex) is None:
        return headers.erreur(400, "TP inconnu")
    return {"sources": state.read_resume(sub, ex)}


@router.put("/brouillon")
def ecrire_brouillon(sub: Sub, corps: BrouillonIn, request: Request):
    """Save the code in progress, to find it again from another machine.

    THE THROTTLE IS CALLED AFTER VALIDATION, and not as a `Depends`: a
    dependency runs before the body, so a request refused for an unknown
    exercise would consume the quota of someone who wrote nothing.
    """
    entree = find_exercise(corps.exercise_id)
    if entree is None:
        return headers.erreur(400, "TP inconnu")
    fichiers, message, code = validate_files(entree, corps.files)
    if message:
        return headers.erreur(code, message)
    freiner_ecriture(request)
    if not state.write_draft(sub, entree["id"], fichiers):
        return headers.erreur(503, "la base ne répond pas")
    return {"ok": True}


@router.get("/preferences")
def lire_preferences(sub: Sub):
    """The theme saved on THIS ACCOUNT, not on this device.

    AN EMPTY THEME IS NOT A FAILURE, and the page must be able to tell them
    apart: "nothing chosen" (200, `theme: ""`) keeps the device's own setting,
    "the database did not answer" (503) touches nothing. Confusing the two
    would overwrite someone's setting on the first outage.
    """
    theme = state.read_theme(sub)
    if theme is None:
        return headers.erreur(503, "la base ne répond pas")
    return {"theme": theme}


@router.put("/preferences")
def ecrire_preferences(sub: Sub, corps: PreferencesIn, request: Request):
    """Save the chosen theme, for all of this account's devices.

    SAME THROTTLE AS THE DRAFT: this is a button, and buttons get clicked. The
    submission quota would be absurd here, and no quota at all would turn a
    repeated click into one Postgres write per click.
    """
    if corps.theme not in state.THEMES:
        return headers.erreur(400, "thème inconnu")
    freiner_ecriture(request)
    if not state.write_theme(sub, corps.theme):
        return headers.erreur(503, "la base ne répond pas")
    return {"ok": True}


@router.delete("/moi")
def effacer(sub: Sub):
    """Erase EVERYTHING kept for this student.

    The consent sentence shown before redirecting to Rauthy promises this
    exists, so it exists -- not "later". `forget()` erases every table of the
    schema, and a test checks this by reading `schema.sql` back.
    """
    if not state.forget(sub):
        return headers.erreur(503, "la base ne répond pas")
    return {"ok": True}
