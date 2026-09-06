"""The peer help forum: six routes, all behind `SubForum`.

NONE OF THEM TAKES A USER ID IN THE REQUEST, and none scans every student's
data: we read ONE exercise thread, or the report queue.

NO `sub` EVER CROSSES THE BOUNDARY. `forum_vue()` translates the author into
"Vous" / "Enseignant" / the chosen name, else "Participant". The moderation
queue copies what is displayed (name, group, message handle) and never the
`account` column used to join.

THE FORUM MUST NEVER PREVENT DOING AN EXERCISE. Disabled, down, or a mute
database: 503 saying so, and "Tester" keeps working.
"""

import re
import uuid

import config
import state
import headers
import security
from deps import SubForum, SubModerateur, freiner_forum
from fastapi import APIRouter, Query, Request
from schemas import (ForumMessageIn, ForumModerationIn, ForumProfilIn,
                     ForumSignalementIn)
from services.catalog import find_exercise
from services import forum as forum_service

# Message and action ids have the same shape as a job (hex uuid4), but they
# are not the same thing: folding them into a single constant would mean that
# the day one of the two shapes changes, the other would change silently
# along with it.
MSG_RE = re.compile(r"\A[0-9a-f]{32}\Z")

router = APIRouter(tags=["forum"])


def _entree(brut):
    """The named catalog entry, or None.

    `find_exercise` is the ONLY gate: there is no thread for an exercise
    absent from the catalog, so no thread to create with a made-up id, and no
    path to traverse.
    """
    return find_exercise(str(brut or ""))


def _message_id(brut):
    """A well-formed message id, or None."""
    valeur = str(brut or "")
    return valeur if MSG_RE.match(valeur) else None


@router.get("/forum")
def fil(sub: SubForum, ex: str = Query("")):
    """An exercise's thread, as THIS caller is allowed to see it."""
    entree = _entree(ex)
    if entree is None:
        return headers.erreur(400, "TP inconnu")
    messages = state.forum_fil(entree["id"], config.FORUM_MAX_FIL)
    if messages is None:
        return headers.erreur(503, "la base ne répond pas")
    moderateur = security.is_moderator(sub)
    profils = state.forum_profils([m["account"] for m in messages]) or {}
    return {
        "exercise_id": entree["id"],
        "moderator": moderateur,
        "max": config.FORUM_MAX_CHARS,
        "messages": forum_service.forum_vue(messages, sub, moderateur, profils),
    }


@router.post("/forum")
def publier(sub: SubForum, corps: ForumMessageIn):
    """Post into a published exercise's thread."""
    entree = _entree(corps.exercise_id)
    if entree is None:
        return headers.erreur(400, "TP inconnu")
    texte, message = forum_service.forum_texte(corps.text)
    if message:
        return headers.erreur(400, message)
    freiner_forum(sub)
    if not state.forum_publier(uuid.uuid4().hex, entree["id"], sub, texte):
        return headers.erreur(503, "la base ne répond pas")
    return {"ok": True}


@router.delete("/forum")
def supprimer(sub: SubForum, id: str = Query("")):
    """Delete THEIR OWN message, never someone else's.

    THE SAME 404 for "this message does not exist" and "it is not yours":
    telling them apart would tell whoever is trying that an id exists.
    """
    message_id = _message_id(id)
    if message_id is None:
        return headers.erreur(400, "identifiant invalide")
    efface = state.forum_supprimer(message_id, sub)
    if efface is None:
        return headers.erreur(503, "la base ne répond pas")
    if not efface:
        return headers.erreur(404, "message introuvable")
    return {"ok": True}


@router.post("/forum/signalement")
def signaler(sub: SubForum, corps: ForumSignalementIn):
    """Report a message, or its author's displayed name.

    THE SAME RESPONSE for a fresh report, a duplicate and an unknown id: that
    is already what the database enforces, and the student does not need to
    learn which of the three cases applies. They reported; someone will read.

    TWO TARGETS, ONE ROUTE. Reporting a name is the same gesture and the same
    queue: the message serves as the handle because the browser has no
    account id, and never will.
    """
    message_id = _message_id(corps.id)
    if message_id is None:
        return headers.erreur(400, "identifiant invalide")
    freiner_forum(sub)
    if corps.kind == "name":
        if state.forum_nom_signaler(message_id, sub) is None:
            return headers.erreur(503, "la base ne répond pas")
        return {"ok": True}
    if state.forum_signaler(message_id, sub) is None:
        return headers.erreur(503, "la base ne répond pas")
    return {"ok": True}


@router.get("/forum/moderation")
def file_moderation(sub: SubModerateur):
    """Reports. Restricted, and the role is recomputed server-side."""
    signales = state.forum_signalements(config.FORUM_MAX_FIL)
    noms = state.forum_noms_signales(config.FORUM_MAX_FIL)
    if signales is None or noms is None:
        return headers.erreur(503, "la base ne répond pas")
    # THE `sub` DOES NOT CROSS HERE EITHER: we copy what is displayed (the
    # reported name, the group, the message handle), never the `account`
    # column used to join them.
    return {"reports": signales, "reported_names": [
        {"id": n["id"], "display_name": n["display_name"], "group_number": n["group_number"],
         "created_at": n["created_at"], "report_count": n["report_count"]}
        for n in noms]}


@router.post("/forum/moderation")
def moderer(sub: SubModerateur, corps: ForumModerationIn):
    """Hide, restore, or clear a name. Three actions, not one more.

    Editing a message is not among them: a message is immutable, and a
    moderator who could correct it could also make someone say something
    else.
    """
    message_id = _message_id(corps.id)
    if message_id is None:
        return headers.erreur(400, "identifiant invalide")
    if corps.action == "clear-name":
        return _effacer_nom(message_id)
    if corps.action not in ("hide", "restore"):
        return headers.erreur(400, "action inconnue")
    fait = state.forum_moderer(uuid.uuid4().hex, message_id, sub, corps.action)
    if fait is None:
        return headers.erreur(503, "la base ne répond pas")
    if not fait:
        return headers.erreur(404, "message introuvable")
    return {"ok": True}


def _effacer_nom(message_id):
    """Clear the NAME of a reported message's author. Nothing else.

    The group number and its visibility stay: what was reported is the name.
    And we WRITE ONE MORE ROW, we correct none -- the journal keeps what the
    name was, which is what a moderator wants to read back.

    NO ROW IN `forum_moderation`: that journal carries a message's `hidden`
    state, and writing "hide-name" there would restore a hidden message as a
    side effect. The profile row's `set_by_moderator` IS this action's
    journal.
    """
    auteur = state.forum_auteur(message_id)
    if not auteur:
        return headers.erreur(404, "message introuvable")
    profil = state.forum_profil(auteur)
    if profil is None:
        return headers.erreur(503, "la base ne répond pas")
    if not state.forum_profil_ecrire(
            uuid.uuid4().hex, auteur, None, profil.get("group_number"), False,
            bool(profil.get("group_number_public")), set_by_moderator=True):
        return headers.erreur(503, "la base ne répond pas")
    return {"ok": True}


@router.get("/forum/profil")
def lire_profil(sub: SubForum, request: Request):
    """THEIR OWN profile, in full. Never someone else's.

    There is no route to read someone else's profile: what is public about a
    profile already arrives through the thread, already filtered.
    """
    profil = state.forum_profil(sub)
    if profil is None:
        return headers.erreur(503, "la base ne répond pas")
    # THE SUGGESTION IS NOT THE PROFILE. It only accompanies a profile as long
    # as it has no name: once chosen, the student's name always takes
    # precedence over the identity provider's.
    return dict(profil, max_display_name=config.FORUM_PSEUDO_MAX,
                group_numbers=list(config.FORUM_GROUPES),
                suggestion=("" if profil.get("display_name")
                            else security.current_name(request.headers)))


@router.post("/forum/profil")
def ecrire_profil(sub: SubForum, corps: ForumProfilIn):
    """Choose a name, a group, and what is shown.

    AN EMPTY FIELD IS NOT A VISIBLE FIELD: without this, checking the box
    without writing anything would display "Participant" while believing
    one had named oneself.
    """
    pseudo, message = forum_service.forum_pseudo(corps.display_name)
    if message:
        return headers.erreur(400, message)
    groupe, message = forum_service.forum_groupe(corps.group_number)
    if message:
        return headers.erreur(400, message)
    freiner_forum(sub)
    if not state.forum_profil_ecrire(
            uuid.uuid4().hex, sub, pseudo, groupe,
            corps.display_name_public and pseudo is not None,
            corps.group_number_public and groupe is not None):
        return headers.erreur(503, "la base ne répond pas")
    return {"ok": True}
