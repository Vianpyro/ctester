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
import secrets
import uuid

import config
import policy
import state
import headers
import security
from deps import SubForum, SubModerateur, freiner_forum
from fastapi import APIRouter, Query, Request
from schemas import (ForumTargetIn, ForumMessageIn, ForumModerationIn,
                     ForumProfilIn, ForumSignalementIn)
from services.catalog import find_exercise
from services import forum as forum_service
from services import leaderboard

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
    messages = state.forum_fil(entree["id"], config.FORUM_MAX_FIL, sub)
    if messages is None:
        return headers.erreur(503, "la base ne répond pas")
    moderateur = security.is_moderator(sub)
    # THE READER'S OWN PROFILE IS READ WITH THE OTHERS, because the visibility
    # rule needs their group number: a `group` message is for people in the
    # author's group, and "my group" is a fact on my profile, not something
    # the request can claim.
    profils = state.forum_profils(
        [m["account"] for m in messages] + [sub]) or {}
    views = forum_service.forum_vue(messages, sub, moderateur, profils)
    return {
        "exercise_id": entree["id"],
        "moderator": moderateur,
        "max": config.FORUM_MAX_CHARS,
        "messages": views,
        # The thread's state, derived from what THIS caller can see (design
        # 1f): a private question nobody else reads must not inflate anyone
        # else's "sans réponse".
        "state": forum_service.thread_state(views),
        # The two closed lists, sent as a legend so the page never has its own
        # copy to drift from -- same split as the mastery bands.
        "steps": [{"id": k, "title": v} for k, v in forum_service.STEPS.items()],
        "blocked_kinds": [{"id": k, "title": v}
                          for k, v in forum_service.BLOCKED_KINDS.items()],
    }


@router.post("/forum")
def publier(sub: SubForum, corps: ForumMessageIn):
    """Post into a published exercise's thread, or ask for help on it.

    ONE ROUTE FOR BOTH, and the difference is `step`: with one, this is a
    "bloqué ici" and it is PRIVATE by default; without, it is the ordinary
    public question the forum has always had. Two routes would mean two places
    to bound a message's length, and the one that drifted would be the one
    that stopped bounding it.

    NO CODE IS EVER TRANSMITTED. The form asks what was observed, not what was
    written -- that is what keeps the charter tenable, and there is no field
    here that could carry a source file.
    """
    entree = _entree(corps.exercise_id)
    if entree is None:
        return headers.erreur(400, "TP inconnu")
    texte, message = forum_service.forum_texte(corps.text)
    if message:
        return headers.erreur(400, message)
    step, message = forum_service.forum_step(corps.step)
    if message:
        return headers.erreur(400, message)
    blocked_kind, message = forum_service.forum_blocked_kind(corps.blocked_kind)
    if message:
        return headers.erreur(400, message)
    visibility, message = forum_service.forum_visibility(
        corps.visibility, step is not None)
    if message:
        return headers.erreur(400, message)
    freiner_forum(sub)
    if not state.forum_publier(uuid.uuid4().hex, entree["id"], sub, texte,
                               step, blocked_kind, visibility):
        return headers.erreur(503, "la base ne répond pas")
    return {"ok": True}


@router.post("/forum/visibility")
def open_to_group(sub: SubForum, corps: ForumTargetIn):
    """Open one's OWN private question to one's group. The only transition.

    PRIVATE -> GROUP, and never the reverse: the reverse would hide what
    others have already read, and that is the immutability social.md sets out.
    The rule is the `WHERE` in `state.forum_open_to_group`, not an `if`
    here -- so two simultaneous clicks cannot race past it.

    THE SAME 404 for "does not exist", "is not yours" and "is not private":
    telling them apart would tell whoever is trying that an id exists.
    """
    message_id = _message_id(corps.id)
    if message_id is None:
        return headers.erreur(400, "identifiant invalide")
    freiner_forum(sub)
    opened = state.forum_open_to_group(message_id, sub)
    if opened is None:
        return headers.erreur(503, "la base ne répond pas")
    if not opened:
        return headers.erreur(404, "message introuvable")
    return {"ok": True}


@router.post("/forum/helpful")
def mark_helpful(sub: SubForum, corps: ForumTargetIn):
    """"Ça m'a aidé" -- a usefulness counter, NOT a popularity vote.

    IT GRANTS NOTHING: no XP, no achievement, no card. A message written to be
    upvoted is a message written for the counter, and this forum has no
    currency for that on purpose.

    ONE'S OWN MESSAGE IS REFUSED IN SQL (`m.account <> %s`), together with the
    duplicate and the made-up id: three races closed by one statement instead
    of three `if`s that each leave one open. All three answer the same 404.
    """
    message_id = _message_id(corps.id)
    if message_id is None:
        return headers.erreur(400, "identifiant invalide")
    freiner_forum(sub)
    marked = state.forum_mark_helpful(message_id, sub)
    if marked is None:
        return headers.erreur(503, "la base ne répond pas")
    if not marked:
        return headers.erreur(404, "message introuvable")
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
    # `retain`/`unretain` MARK THE ANSWER THE COURSE STANDS BEHIND, and they
    # edit nothing: the action goes into the append-only journal, and the
    # latest one for a message is the answer (see `state.forum_fil`).
    # Epingler n'edite rien -- a message stays immutable, which is what keeps
    # a report readable.
    if corps.action not in ("hide", "restore", "retain", "unretain"):
        return headers.erreur(400, "action inconnue")
    fait = state.forum_moderer(uuid.uuid4().hex, message_id, sub, corps.action)
    if fait is None:
        return headers.erreur(503, "la base ne répond pas")
    if not fait:
        return headers.erreur(404, "message introuvable")
    return {"ok": True}


# HOURS, NOT DAYS: this is a live view of a lab session. A window of a week
# would mix Tuesday's group with Thursday's and count nobody's room.
HELP_WINDOW_HOURS = 8


@router.get("/forum/help")
def who_needs_help(sub: SubModerateur):
    """"Qui a besoin d'aide", aggregated by exercise and step (design 1h).

    COUNTS AND STEPS, NEVER PEOPLE. No `sub`, no name, no text, no code: a
    number is what says where to walk in the room, and six people on the same
    conversion is one explanation at the board rather than six replies.

    PRIVATE QUESTIONS ARE COUNTED, NOT REVEALED. They stay unreadable -- only
    their author can open one to their group -- and this row says only that a
    number exists. That is the whole compromise, and it is written on the
    student's form: "seulement le chargé de lab".

    RESTRICTED, and the role is recomputed server-side from the token on every
    call, like every other moderator route.
    """
    rows = state.forum_help_rows(config.FORUM_MAX_FIL, HELP_WINDOW_HOURS)
    if rows is None:
        return headers.erreur(503, "la base ne répond pas")
    return {"rows": rows, "hours": HELP_WINDOW_HOURS,
            "steps": [{"id": k, "title": v} for k, v in forum_service.STEPS.items()],
            "blocked_kinds": [{"id": k, "title": v}
                              for k, v in forum_service.BLOCKED_KINDS.items()]}


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
    # EVERY OTHER FIELD IS CARRIED OVER, and that is not optional: the latest
    # row IS the profile, so a write that left out the alias, the frame or the
    # leaderboard opt-in would silently reset them. Clearing a name must clear
    # the name and nothing else -- the group number is the case that was
    # already written down, and the three added since behave the same way.
    if not state.forum_profil_ecrire(
            uuid.uuid4().hex, auteur, None, profil.get("group_number"), False,
            bool(profil.get("group_number_public")), set_by_moderator=True,
            alias=profil.get("alias"), plate_frame=profil.get("plate_frame"),
            badges_public=profil.get("badges_public"),
            leaderboard_opt_in=profil.get("leaderboard_opt_in")):
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
    #
    # THE UNLOCKED FRAMES ARE COMPUTED HERE, from the level the account
    # actually reached: the form must offer what is available, and "what is
    # available" is a fact about the account, never something the browser
    # asserts. A mute progression is not an error here -- the identity form
    # must keep working when the ranking cannot be read -- so it falls back to
    # the first frame, which is always open.
    facts = state.read_progress(sub)
    rank = policy.niveau(facts["xp"])["rank"] if facts else 1
    return dict(profil, max_display_name=config.FORUM_PSEUDO_MAX,
                group_numbers=list(config.FORUM_GROUPES),
                frames=policy.unlocked_frames(rank),
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
    previous = state.forum_profil(sub)
    if previous is None:
        return headers.erreur(503, "la base ne répond pas")
    facts = state.read_progress(sub)
    frame, message = forum_service.forum_frame(
        corps.plate_frame,
        policy.unlocked_frames(policy.niveau(facts["xp"])["rank"] if facts else 1))
    if message:
        return headers.erreur(400, message)
    # JOINING A RANKING NEEDS AN ALIAS, and it is drawn here rather than
    # refused: someone who ticks the box must land in the ranking, not in an
    # error telling them to go press another button first. Redrawing it stays
    # available, as often as they like.
    alias = previous.get("alias")
    if corps.leaderboard_opt_in and not alias:
        taken = state.forum_taken_aliases()
        if taken is None:
            return headers.erreur(503, "la base ne répond pas")
        alias = leaderboard.draw_alias(taken, secrets.randbelow(1 << 32))
    freiner_forum(sub)
    if not state.forum_profil_ecrire(
            uuid.uuid4().hex, sub, pseudo, groupe,
            corps.display_name_public and pseudo is not None,
            corps.group_number_public and groupe is not None,
            alias=alias, plate_frame=frame,
            badges_public=corps.badges_public,
            leaderboard_opt_in=corps.leaderboard_opt_in):
        return headers.erreur(503, "la base ne répond pas")
    return {"ok": True}
