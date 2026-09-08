"""Team assignments: the shared workspace, its history, and the hand-in.

EVERY ROUTE HERE GOES THROUGH THE SAME TWO LINES, and that is the whole
security story:

    assignment, team, refusal = teams.workspace(state, sub, assignment_id)
    if refusal: ...                       # 404 / 400 / 403, never a document
    if not teams.exercise_in(assignment, exercise_id): ...

`sub` comes from the validated token (`Sub`), the team comes from Postgres,
and the exercise must belong to the assignment the team was proven for. No
route -- and no WebSocket frame -- reads a team id from the client. Changing
an id in a URL, a body or a socket message therefore reaches nothing: there is
no id to change.

THE INDIVIDUAL PATH IS UNTOUCHED. `/brouillon` still writes
`exercise_draft` keyed on (account, exercise); nothing here writes to it, and
an exercise that belongs to no assignment never reaches this router.
"""

import asyncio
import json
import uuid

import config
import deps
import headers
import security
import state
from deps import Sub, freiner_ecriture
from fastapi import APIRouter, Query, Request, WebSocket
from schemas import (TeamDocumentIn, TeamHandinIn, TeamJoinIn, TeamLeaveIn,
                     TeamRestoreIn)
from services import collab
from services import teams as team_service
from services.catalog import find_exercise, validate_files
from starlette.concurrency import run_in_threadpool
from starlette.responses import Response

router = APIRouter(tags=["equipe"])

# What a hand-in frame may weigh, and what a collaboration frame may weigh.
# Both are bounded here rather than trusted: the middleware bounds HTTP bodies
# before parsing, but a WebSocket frame never passes through it.
MAX_FRAME = config.TEAM_LIVE_MAX_FRAME


def _gate(sub, assignment_id, exercise_id=None):
    """(assignment, team, error response) -- the two lines, in one place.

    Written once so that a route added next term cannot forget the second
    half: proving the team without proving the exercise would let a member of
    one team open a document keyed on their team and any exercise at all.
    """
    assignment, team, refusal = team_service.workspace(state, sub, assignment_id)
    if refusal:
        return None, None, headers.erreur(*refusal)
    if exercise_id is not None and not team_service.exercise_in(assignment, exercise_id):
        # THE SAME ANSWER AS AN UNKNOWN EXERCISE, on purpose: "that exercise
        # exists but not in your assignment" is a fact about someone else's
        # assignment, and it is not ours to hand out.
        return None, None, headers.erreur(404, "exercice inconnu pour ce devoir")
    return assignment, team, None


def _roster(assignment_id, team_id):
    """The team's accounts, or None when the database did not answer."""
    return state.team_roster(assignment_id, team_id)


@router.get("/team/context")
def context(sub: Sub, assignment: str = Query("", alias="assignment")):
    """The workspace's header: the assignment, the team, its members, the hand-in.

    ONE ROUND TRIP FOR THE WHOLE HEADER. The page opens this once when an
    assignment exercise is selected; every subsequent exercise switch reuses
    it, which is what makes the strip feel local rather than like six page
    loads.
    """
    entry, team, refused = _gate(sub, assignment)
    if refused is not None:
        return refused
    roster = _roster(entry["id"], team["team_id"])
    if roster is None:
        return headers.erreur(503, "la base ne répond pas")
    profiles = state.forum_profils(roster) or {}
    submission = state.read_team_submission(entry["id"], team["team_id"])
    if submission is None:
        return headers.erreur(503, "la base ne répond pas")
    return {
        "assignment": team_service.assignment_view(entry),
        # THE TEAM'S OWN ID IS RETURNED, and that is not a contradiction: it
        # is the id of the team the SERVER just proved this account belongs
        # to. Sending it back lets the page name the workspace; sending it in
        # a request would be the hole, and no route reads one.
        "team": {"id": team["team_id"],
                 "label": team["label"] or team_service.TEAM_NAME % team["number"],
                 "number": team["number"], "group_number": team["group_number"],
                 "members": team_service.members_view(roster, sub, profiles)},
        "submission": submission,
    }


# --- Rejoindre une équipe --------------------------------------------------------
# TROIS ROUTES, ET ELLES RÉPONDENT AVANT QUE LE DEVOIR N'OUVRE : les équipes se
# choisissent en septembre, le devoir ouvre en octobre. Elles passent donc par
# `published_assignment()` -- montrer n'est pas donner -- et jamais par
# `workspace()`, qui exige un devoir OUVERT.
#
# ET C'EST CE QUI LES REND MUTUELLEMENT EXCLUSIVES : `joinable()` demande que
# le devoir soit fermé, `find_assignment()` qu'il soit ouvert, et les deux
# lisent la MÊME valeur. Il n'existe aucun instant où l'on peut à la fois
# rejoindre une équipe et lire son document -- pas parce qu'on l'a vérifié,
# mais parce que c'est la même condition prise dans les deux sens.


def _choix(sub, assignment_id):
    """(assignment, groupe, erreur) -- la porte du CHOIX d'équipe.

    Elle exige trois choses, et refuse chacune avec sa phrase : un devoir
    publié, un devoir D'ÉQUIPE, et un devoir PAS ENCORE OUVERT.

    LE GROUPE VIENT DU PROFIL, et c'est le seul endroit où ce numéro
    auto-déclaré décide de quelque chose : QUELLE LISTE on voit. Il ne donne
    accès à rien -- une fois dans une équipe, c'est ELLE qui porte son groupe,
    et le corriger ensuite ne déplace personne. Sans lui, on ne sait pas quelle
    liste montrer, et la réponse le dit plutôt que d'en montrer une au hasard.
    """
    entry = team_service.published_assignment(assignment_id)
    if entry is None:
        return None, None, headers.erreur(404, "devoir inconnu")
    if not team_service.is_team_assignment(entry):
        return None, None, headers.erreur(
            400, "ce devoir n'est pas un travail d'équipe")
    if not team_service.joinable(entry):
        return None, None, headers.erreur(
            409, "les équipes sont figées : le devoir est ouvert")
    profil = state.forum_profil(sub) or {}
    groupe = profil.get("group_number")
    if groupe is None:
        return None, None, headers.erreur(
            409, "choisis d'abord ton groupe dans « Mon identité » : les "
                 "équipes sont numérotées par groupe")
    return entry, int(groupe), None


@router.get("/team/available")
def available(sub: Sub, assignment: str = Query("")):
    """Les équipes de MON groupe, avec leurs places libres.

    LA MÊME LISTE QUE MOODLE, et les mêmes numéros -- c'est tout l'intérêt :
    un étudiant qui prend « Équipe 7 » ici doit retrouver « Équipe 7 » là-bas,
    sinon l'enseignant tient deux listes qui divergent.

    AUCUN `sub` N'EN SORT, et pas même un nom : une liste de choix n'a pas à
    dire QUI est dans quelle équipe. « 3/4 » suffit à choisir, et publier les
    compositions ferait de ce choix un tri social sur une page.
    """
    entry, groupe, refused = _choix(sub, assignment)
    if refused is not None:
        return refused
    existantes = state.team_counts(entry["id"], groupe)
    if existantes is None:
        return headers.erreur(503, "la base ne répond pas")
    mienne = state.team_of(sub, entry["id"])
    return {"assignment_id": entry["id"], "group_number": groupe,
            "mine": mienne["number"] if mienne else None,
            "teams": team_service.available_teams(entry, groupe, existantes)}


@router.post("/team/join")
def join(sub: Sub, corps: TeamJoinIn, request: Request):
    """Prendre une place. L'ÉQUIPE EST CRÉÉE si personne n'y était encore.

    LE NUMÉRO EST BORNÉ PAR LE CONTENU, pas par la requête : au-delà de
    `team.count`, l'équipe n'existe pas -- et elle n'existe pas non plus dans
    Moodle, ce qui est exactement le point.

    LA PLACE EST COMPTÉE DANS LE `WHERE` DE L'INSERT, jamais relue avant :
    deux étudiants qui cliquent sur la dernière place au même instant
    passeraient tous les deux un `if`.
    """
    entry, groupe, refused = _choix(sub, corps.assignment_id)
    if refused is not None:
        return refused
    if state.team_of(sub, entry["id"]) is not None:
        return headers.erreur(
            409, "tu es déjà dans une équipe : quitte-la d'abord")
    _low, high, count = team_service.team_size(entry)
    if not 1 <= corps.number <= count:
        return headers.erreur(
            404, "cette équipe n'existe pas (il y en a %d)" % count)
    team_id = team_service.team_handle(groupe, corps.number)
    freiner_ecriture(request)
    if not state.team_join(sub, entry["id"], team_id, groupe, corps.number,
                           team_service.TEAM_NAME % corps.number, high):
        return headers.erreur(
            409, "cette équipe est complète (%d places)" % high)
    return available(sub, entry["id"])


@router.post("/team/leave")
def leave(sub: Sub, corps: TeamLeaveIn, request: Request):
    """Quitter, TANT QUE LE DEVOIR N'EST PAS OUVERT.

    Après, non : le document est déjà le travail de tous, et partir le
    laisserait à trois personnes qui n'ont pas choisi ça. `_choix()` porte la
    condition, comme pour rejoindre -- c'est la même date, prise au même
    endroit.

    L'ÉQUIPE VIDÉE RESTE : elle porte peut-être déjà un document, et son
    numéro est celui de Moodle. Une équipe vide se remplit à nouveau ; une
    équipe supprimée renumérote tout.
    """
    entry, _groupe, refused = _choix(sub, corps.assignment_id)
    if refused is not None:
        return refused
    if state.team_of(sub, entry["id"]) is None:
        return headers.erreur(404, "tu n'es dans aucune équipe pour ce devoir")
    freiner_ecriture(request)
    if not state.team_leave(sub, entry["id"]):
        return headers.erreur(503, "la base ne répond pas")
    return available(sub, entry["id"])


@router.get("/team/mine")
def mine(sub: Sub):
    """Which teams this account is on. READ-ONLY, AND IT OPENS NOTHING.

    THE ONE ROUTE THAT ANSWERS BEFORE THE ASSIGNMENT DOES. Every other route
    here goes through `workspace()`, which refuses an assignment that is not
    open yet -- correctly, since there is nothing to work on. But the roster is
    loaded BEFORE the first class, and "am I on the right team, with the right
    people?" is exactly the question a student must be able to ask then. A
    student who can only find out on the morning of the deadline finds out too
    late.

    SHOWING IS NOT GIVING -- the same rule the catalog already follows by
    carrying a locked exercise with its date. This returns a label, a group
    number, teammates as POSITIONS, and the assignment's opening date. No
    document, no revision, no room: those still go through the gate.
    """
    rows = state.team_memberships(sub)
    if rows is None:
        return headers.erreur(503, "la base ne répond pas")
    out = []
    for row in rows:
        entry = team_service.published_assignment(row["assignment_id"])
        if entry is None:
            # A roster loaded for an assignment that is no longer published.
            # Not an error, and not this student's problem: say nothing rather
            # than name a devoir they cannot open.
            continue
        roster = _roster(row["assignment_id"], row["team_id"])
        if roster is None:
            return headers.erreur(503, "la base ne répond pas")
        profiles = state.forum_profils(roster) or {}
        out.append({
            "assignment_id": entry["id"],
            "assignment_title": entry.get("title", ""),
            "access": entry.get("access", "archived"),
            "available_from": (entry.get("release") or {}).get("available_from"),
            "deadline": entry.get("deadline"),
            # ENCORE MODIFIABLE ? C'est la même date que `joinable()`, rendue
            # ici pour que la page sache s'il faut dessiner « Changer
            # d'équipe » ou expliquer que c'est figé.
            "joinable": team_service.joinable(entry),
            "number": row["number"],
            "label": row["label"] or team_service.TEAM_NAME % row["number"],
            "group_number": row["group_number"],
            "members": team_service.members_view(roster, sub, profiles),
        })
    return {"teams": out}


@router.get("/team/document")
def read_document(sub: Sub, assignment: str = Query(""), ex: str = Query("")):
    """The team's shared sources for one exercise -- the CRDT's seed.

    AN EMPTY WORKSPACE IS NOT A FAILURE, and the two are told apart: `{}` is a
    team that has not started, 503 is a database that did not answer. Confusing
    them would have the first member into a room seed the document from
    nothing and quietly overwrite an afternoon.
    """
    entry, team, refused = _gate(sub, assignment, ex)
    if refused is not None:
        return refused
    sources = state.read_team_document(team["team_id"], ex)
    if sources is None:
        return headers.erreur(503, "la base ne répond pas")
    catalog_entry = find_exercise(ex)
    if catalog_entry is not None and sources:
        checked, message, _ = validate_files(catalog_entry, sources)
        sources = checked if message is None else {}
    return {"exercise_id": ex, "sources": sources}


@router.put("/team/document")
def write_document(sub: Sub, corps: TeamDocumentIn, request: Request):
    """Persist the shared document, and a revision when one is worth keeping.

    WHOEVER TYPED IS WHOEVER SAVES. The page only calls this after a LOCAL
    edit -- never when a teammate's change arrives over the socket -- so the
    account attached to a revision is the account that wrote it, not whichever
    of the four happened to have the tab focused.

    THE THROTTLE COMES AFTER VALIDATION, as everywhere else: a request refused
    for an unknown exercise must not spend the quota of someone who wrote
    nothing.
    """
    entry, team, refused = _gate(sub, corps.assignment_id, corps.exercise_id)
    if refused is not None:
        return refused
    catalog_entry = find_exercise(corps.exercise_id)
    if catalog_entry is None:
        return headers.erreur(404, "exercice inconnu pour ce devoir")
    files, message, code = validate_files(catalog_entry, corps.files)
    if message:
        return headers.erreur(code, message)
    freiner_ecriture(request)
    if not state.write_team_document(team["team_id"], corps.exercise_id, sub,
                                     files, uuid.uuid4().hex,
                                     config.TEAM_REVISION_WINDOW):
        return headers.erreur(503, "la base ne répond pas")
    return {"ok": True}


@router.get("/team/revisions")
def revisions(sub: Sub, assignment: str = Query(""), ex: str = Query("")):
    """The document's history: who, when, how big. Never the text.

    THE AUTHOR IS A TEAM POSITION, NOT AN ACCOUNT (`revisions_view`), and
    there is no percentage anywhere in the payload -- a contribution figure
    would become a grade the day after it shipped.
    """
    entry, team, refused = _gate(sub, assignment, ex)
    if refused is not None:
        return refused
    roster = _roster(entry["id"], team["team_id"])
    rows = state.read_team_revisions(team["team_id"], ex,
                                     config.TEAM_REVISIONS_MAX)
    if rows is None or roster is None:
        return headers.erreur(503, "la base ne répond pas")
    return {"exercise_id": ex,
            "revisions": team_service.revisions_view(rows, roster)}


@router.get("/team/revision")
def revision(sub: Sub, assignment: str = Query(""), ex: str = Query(""),
             id: str = Query("")):
    """One revision's sources, for reading before restoring.

    THE TEAM IS IN THE `WHERE` (`read_team_revision`): an id belonging to
    another team resolves to nothing, so there is no ownership check here to
    forget.
    """
    entry, team, refused = _gate(sub, assignment, ex)
    if refused is not None:
        return refused
    sources = state.read_team_revision(team["team_id"], id)
    if sources is None:
        return headers.erreur(503, "la base ne répond pas")
    if not sources:
        return headers.erreur(404, "révision inconnue")
    return {"revision_id": id, "sources": sources}


@router.post("/team/restore")
def restore(sub: Sub, corps: TeamRestoreIn, request: Request):
    """Put an earlier revision back into the shared document.

    RESTORING IS A WRITE, NOT A REWIND. It saves the old text as the current
    document, under the account that restored it -- so the history keeps
    growing forwards and nobody's afternoon disappears from it. A team that
    restores by mistake restores again.

    THE LIVE ROOM IS NOT NOTIFIED, and the page handles that honestly: it
    applies the restored text through the editor, i.e. as an ordinary local
    edit, so teammates receive it as a change like any other. A server-side
    push into the CRDT would mean this process understanding Yjs, which is
    exactly what `services/collab.py` exists not to do.
    """
    entry, team, refused = _gate(sub, corps.assignment_id, corps.exercise_id)
    if refused is not None:
        return refused
    catalog_entry = find_exercise(corps.exercise_id)
    if catalog_entry is None:
        return headers.erreur(404, "exercice inconnu pour ce devoir")
    sources = state.read_team_revision(team["team_id"], corps.revision_id)
    if sources is None:
        return headers.erreur(503, "la base ne répond pas")
    if not sources:
        return headers.erreur(404, "révision inconnue")
    files, message, code = validate_files(catalog_entry, sources)
    if message:
        return headers.erreur(code, message)
    freiner_ecriture(request)
    if not state.write_team_document(team["team_id"], corps.exercise_id, sub,
                                     files, uuid.uuid4().hex, 0):
        return headers.erreur(503, "la base ne répond pas")
    return {"ok": True, "sources": files}


def _handin(sub, assignment_id):
    """(assignment, team, files, missing, error). Shared by the ZIP and the hand-in.

    ONE BUILDER FOR BOTH, because "what I downloaded" and "what I handed in"
    diverging is the failure this feature would be remembered for.
    """
    entry, team, refused = _gate(sub, assignment_id)
    if refused is not None:
        return None, None, None, None, refused
    if not (entry.get("handin") or {}).get("files"):
        return None, None, None, None, headers.erreur(
            400, "ce devoir ne déclare pas de remise")
    files, missing = team_service.handin_files(state, entry, team["team_id"],
                                               find_exercise)
    if files is None:
        return None, None, None, None, headers.erreur(503, "la base ne répond pas")
    return entry, team, files, missing, None


@router.get("/team/handin.zip")
def handin_zip(sub: Sub, assignment: str = Query("")):
    """The team's hand-in, as the archive that gets uploaded to Moodle.

    BUILT SERVER-SIDE, FROM THE TEAM'S OWN DOCUMENTS. The browser sends
    nothing but the assignment id: an archive assembled from the editor would
    be an archive of one member's tab, and the team would find out at marking
    time.

    DETERMINISTIC (see `build_zip`): the same documents produce the same bytes,
    which is what makes it testable at all.
    """
    entry, team, files, missing, refused = _handin(sub, assignment)
    if refused is not None:
        return refused
    if not files:
        return headers.erreur(400, "il n'y a encore rien à remettre")
    body = team_service.build_zip(files)
    return Response(body, media_type="application/zip", headers={
        "Content-Disposition": 'attachment; filename="%s"'
                               % team_service.archive_name(entry, team),
        # A HAND-IN IS NOT A FILE TO CACHE. It is account data, like every
        # other response of this API; `no-store` is the middleware's default
        # and it is restated here because this one leaves as a binary.
        "Cache-Control": "no-store",
    })


@router.post("/team/handin")
def handin(sub: Sub, corps: TeamHandinIn, request: Request):
    """Hand in, once per team. The primary key is what "once" means.

    HANDING IN AGAIN REPLACES IT, and that is deliberate: a team that finds a
    bug at 22:00 must be able to fix it, and `team_revision` still holds what
    was there before. What cannot happen is two hand-ins coexisting for one
    team -- `team_submission`'s primary key refuses that, not an `if`.

    A HOLE IS REFUSED RATHER THAN HANDED IN. If a declared file has no
    content, the request comes back saying which -- handing in an archive
    missing `matrac_lib.c` is the failure nobody notices until the mark.
    """
    entry, team, files, missing, refused = _handin(sub, corps.assignment_id)
    if refused is not None:
        return refused
    if team_service.deadline_passed(entry):
        return headers.erreur(403, "la date de remise est passée")
    if missing:
        return headers.erreur(
            400, "remise incomplète : " + ", ".join(m["name"] for m in missing))
    freiner_ecriture(request)
    if not state.write_team_submission(entry["id"], team["team_id"], sub, files):
        return headers.erreur(503, "la base ne répond pas")
    submission = state.read_team_submission(entry["id"], team["team_id"])
    return {"ok": True, "submission": submission or {},
            "files": sorted(files)}


# --- The collaboration socket ---------------------------------------------------
# THE TOKEN ARRIVES IN THE FIRST MESSAGE, NOT IN THE URL. A browser cannot set
# an `Authorization` header on a WebSocket, and the two usual workarounds are a
# query parameter -- which every proxy in the path writes to a log file -- and
# the subprotocol trick, which is obscure enough that the next person to read
# it would have to look it up. A first frame is neither: the socket is accepted,
# the client says who it is, and anything else closes it.
#
# THE SERVER STAMPS THE SENDER ON EVERY RELAYED FRAME. A member cannot claim
# another member's caret, because the `from` field is not read from what they
# sent -- it is the handle the roster gave them when the socket opened.

# LES CODES VIVENT DANS `deps`, PAS ICI. `/scratch/live` parle le même
# dialecte, et deux tables de codes sont deux tables qui divergent -- celle qui
# dériverait est celle qu'on relit le moins. Un test refuse qu'un routeur les
# redéclare.
CLOSE_UNAUTHORIZED = deps.CLOSE_UNAUTHORIZED
CLOSE_FORBIDDEN = deps.CLOSE_FORBIDDEN
CLOSE_BUSY = deps.CLOSE_BUSY
CLOSE_BAD = deps.CLOSE_BAD

# The frame kinds relayed verbatim. THE PAYLOAD IS NEVER PARSED: `d` is
# base64 of whatever Yjs produced, and this process has no opinion about it.
RELAYED = ("sync", "update", "cursor")


@router.websocket("/team/live")
async def live(socket: WebSocket):
    """One member, one exercise, one room. Relay only.

    The sequence is fixed and short: accept, read the hello frame, authorize,
    join, announce, then loop. Every step that fails closes the socket with a
    code the page can tell apart -- a student whose session expired and a
    student who is not on a team must not both read "connection lost".
    """
    # THE ORIGIN IS CHECKED BEFORE ANYTHING ELSE. A WebSocket is not subject
    # to CORS: the browser opens it to any host and only sends `Origin`. The
    # token in the first frame is already the real barrier -- a hostile page
    # cannot read another origin's `sessionStorage` -- but refusing an unknown
    # origin here costs one comparison and closes the door earlier. An ABSENT
    # `Origin` is accepted: that is a non-browser client, which has to know a
    # valid token anyway.
    origin = socket.headers.get("origin", "").strip().rstrip("/")
    if origin and origin not in config.ORIGINS:
        await socket.close(code=CLOSE_FORBIDDEN)
        return
    await socket.accept()
    try:
        hello = await asyncio.wait_for(socket.receive_text(), timeout=10)
    except Exception:
        await socket.close(code=CLOSE_BAD)
        return
    try:
        opening = json.loads(hello)
    except ValueError:
        opening = None
    if not isinstance(opening, dict) or opening.get("t") != "hello":
        await socket.close(code=CLOSE_BAD)
        return

    token = opening.get("token")
    assignment_id = opening.get("assignment")
    exercise_id = opening.get("exercise")
    if not all(isinstance(v, str) and v for v in (token, assignment_id, exercise_id)):
        await socket.close(code=CLOSE_BAD)
        return

    # `current_user` AND `team_of` BOTH BLOCK: one calls the issuer, the other
    # talks to Postgres behind the global lock. In the threadpool, like every
    # HTTP endpoint of this application -- awaiting them on the event loop
    # would stall every other socket for the duration of a cold token.
    sub = await run_in_threadpool(security.current_user,
                                  {"Authorization": "Bearer " + token})
    if not sub:
        await socket.close(code=CLOSE_UNAUTHORIZED)
        return

    def resolve():
        assignment, team, refusal = team_service.workspace(state, sub, assignment_id)
        if refusal or not team_service.exercise_in(assignment, exercise_id):
            return None, None, None
        return assignment, team, state.team_roster(assignment["id"], team["team_id"])

    assignment, team, roster = await run_in_threadpool(resolve)
    if team is None or roster is None:
        await socket.close(code=CLOSE_FORBIDDEN)
        return

    key = collab.room_key(team["team_id"], exercise_id)
    if collab.full(key):
        await socket.close(code=CLOSE_BUSY)
        return
    connection = collab.Connection(socket, key,
                                   team_service.member_handle(roster, sub), sub)
    epoch, peers = collab.join(connection)
    try:
        # `peers` DECIDES WHO SEEDS THE DOCUMENT: the first client into an
        # empty room fills its Yjs document from `GET /team/document`, later
        # ones ask the room. `epoch` is what a reconnecting client compares
        # against -- a different one means the room was rebuilt while it was
        # away, so its local copy must be dropped rather than merged.
        await connection.send({"t": "ready", "epoch": epoch, "peers": peers,
                               "me": connection.handle,
                               "exercise": exercise_id})
        await collab.announce(key)
        while True:
            raw = await socket.receive_text()
            if len(raw) > MAX_FRAME:
                await socket.close(code=CLOSE_BAD)
                return
            try:
                frame = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(frame, dict) or frame.get("t") not in RELAYED:
                continue
            # THE SENDER IS OURS, THE PAYLOAD IS THEIRS. `from` is overwritten
            # with the handle this socket was given; nothing the client wrote
            # into it survives.
            frame["from"] = connection.handle
            frame.pop("token", None)
            await collab.broadcast(connection, frame)
    except Exception:
        # A closed socket, a dropped connection, a browser that went to sleep:
        # all the same thing here, and none of them is an error to report.
        pass
    finally:
        collab.leave(connection)
        await collab.announce(key)


@router.get("/team/roster")
def roster_view(sub: Sub, assignment: str = Query("")):
    """The instructor's view: the teams of one assignment, and their sizes.

    MODERATOR ONLY, recomputed here from the authenticated `sub` like every
    other role check in this application. It carries no `sub`, no name, no
    document and no code -- a roster is "how many teams, how big", and the
    work itself is read through the workspace by someone who is on the team.
    """
    if not security.is_moderator(sub):
        return headers.erreur(403, "réservé à l'enseignant")
    entry = team_service.find_assignment(assignment)
    if entry is None:
        return headers.erreur(404, "devoir inconnu")
    rows = state.read_teams(entry["id"])
    if rows is None:
        return headers.erreur(503, "la base ne répond pas")
    return {"assignment_id": entry["id"], "teams": rows}
