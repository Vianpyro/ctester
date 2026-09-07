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
import headers
import security
import state
from deps import Sub, freiner_ecriture
from fastapi import APIRouter, Query, Request, WebSocket
from schemas import (TeamDocumentIn, TeamFormIn, TeamHandinIn, TeamJoinIn,
                     TeamLeaveIn, TeamLockIn, TeamRestoreIn)
from services import collab
from services import teams as team_service
from services.catalog import find_exercise, validate_files
from services.forum import forum_groupe
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
        "team": {"id": team["team_id"], "label": team["label"] or team["team_id"],
                 "group_number": team["group_number"],
                 "members": team_service.members_view(
                     roster, sub, profiles,
                     state.team_locks(entry["id"], team["team_id"]))},
        "submission": submission,
    }


# --- Se former une équipe --------------------------------------------------------
# CES CINQ ROUTES SONT LES SEULES QUI ÉCRIVENT DANS `team` ET `team_member`,
# et elles répondent toutes avant que le devoir n'ouvre : le listage se
# constitue AVANT le premier cours, et c'est là qu'une erreur se corrige
# encore. Elles passent donc par `published_assignment()` -- montrer n'est pas
# donner -- et jamais par `workspace()`, qui exige une équipe SCELLÉE.
#
# `workspace()` EST TOUJOURS LA PORTE du document, de l'historique, de la
# salle et de la remise. Rien de ce qui suit n'ouvre quoi que ce soit : former
# une équipe et travailler sont deux choses, et c'est le scellement qui fait
# passer de l'une à l'autre.


def _forming(sub, assignment_id):
    """(assignment, team|None, min, max, erreur) -- la porte de la FORMATION.

    Elle laisse passer ce que `workspace()` refuse -- un devoir pas encore
    ouvert, une équipe pas encore scellée -- parce que c'est exactement le
    moment où ces routes servent. Ce qu'elle exige quand même : un devoir
    publié, et un devoir d'ÉQUIPE.
    """
    entry = team_service.published_assignment(assignment_id)
    if entry is None:
        return None, None, 0, 0, headers.erreur(404, "devoir inconnu")
    if not team_service.is_team_assignment(entry):
        return None, None, 0, 0, headers.erreur(
            400, "ce devoir n'est pas un travail d'équipe")
    low, high = team_service.team_size(entry)
    return entry, state.team_of(sub, assignment_id), low, high, None


def _mon_equipe(sub, entry, team):
    """L'équipe telle que ses membres la voient pendant la formation.

    LES MÊMES POSITIONS QUE PARTOUT AILLEURS, plus qui a confirmé -- « on
    attend Coéquipier 3 » est ce qui rend une équipe bloquée compréhensible
    sans écrire à personne.
    """
    roster = state.team_roster(entry["id"], team["team_id"])
    locks = state.team_locks(entry["id"], team["team_id"])
    if roster is None or locks is None:
        return None
    profiles = state.forum_profils(roster) or {}
    return {
        "id": team["team_id"],
        "label": team["label"] or team["team_id"],
        "group_number": team["group_number"],
        # LE CODE NE SORT QUE POUR UN MEMBRE, et `team_of` l'a déjà retiré
        # d'une équipe scellée : après, il n'ouvre plus rien.
        "invite_code": team.get("invite_code"),
        "sealed": bool(team.get("sealed")),
        "locked": bool(team.get("locked")),
        "missing": team_service.formation_state(entry, team, locks),
        "members": team_service.members_view(roster, sub, profiles, locks),
    }


@router.post("/team/create")
def create(sub: Sub, corps: TeamFormIn, request: Request):
    """Créer son équipe. Le créateur y entre, et reçoit le code à partager.

    L'IDENTIFIANT EST TIRÉ PAR LE SERVEUR, jamais choisi : il clé le document
    partagé et nomme la salle de collaboration, et un identifiant choisi par
    un étudiant serait un identifiant qu'un autre pourrait deviner. Ce que les
    gens lisent, c'est `label`.
    """
    entry, team, _low, _high, refused = _forming(sub, corps.assignment_id)
    if refused is not None:
        return refused
    if team is not None:
        return headers.erreur(
            409, "tu es déjà dans une équipe pour ce devoir")
    label, message = team_service.team_label(corps.label)
    if message:
        return headers.erreur(400, message)
    group, message = forum_groupe(corps.group_number)
    if message:
        return headers.erreur(400, message)
    freiner_ecriture(request)
    # LE CODE EST TIRÉ, ET UNE COLLISION SE REJOUE. L'index unique la refuse,
    # `team_create` rend None, on retire. Cinq échecs de suite ne sont pas de
    # la malchance sur 31^6 -- c'est une base qui ne répond pas.
    for _ in range(team_service.CODE_TRIES):
        code = team_service.invite_code()
        team_id = state.team_create(sub, entry["id"], uuid.uuid4().hex[:12],
                                    label, group, code)
        if team_id:
            break
    else:
        return headers.erreur(503, "la base ne répond pas")
    _entry, team, _low, _high, refused = _forming(sub, corps.assignment_id)
    vue = _mon_equipe(sub, entry, team) if team else None
    if vue is None:
        return headers.erreur(503, "la base ne répond pas")
    return {"team": vue}


@router.post("/team/join")
def join(sub: Sub, corps: TeamJoinIn, request: Request):
    """Rejoindre avec le code. LE `WHERE` DE L'INSERT EST LE CONTRÔLE D'ACCÈS.

    QUATRE REFUS, QUATRE PHRASES. « ce code ne correspond à rien », « cette
    équipe est déjà confirmée », « elle est complète » et « tu es déjà dans une
    équipe » envoient à quatre endroits différents ; un seul message les
    enverrait tous les quatre redemander le code à quelqu'un qui l'a bien donné.
    """
    entry, team, _low, high, refused = _forming(sub, corps.assignment_id)
    if refused is not None:
        return refused
    if team is not None:
        return headers.erreur(409, "tu es déjà dans une équipe pour ce devoir")
    code = (corps.code or "").strip().upper()
    freiner_ecriture(request)
    if not state.team_join(sub, entry["id"], code, high):
        # RIEN N'A ÉTÉ ÉCRIT : on relit pour DIRE POURQUOI. Sans ça, une
        # équipe complète et un code inventé sont le même échec.
        cible = state.team_by_code(entry["id"], code)
        if cible is None:
            return headers.erreur(404, "ce code ne correspond à aucune équipe")
        if cible["sealed"]:
            return headers.erreur(
                409, "cette équipe est déjà confirmée : elle ne peut plus "
                     "accueillir personne")
        if cible["members"] >= high:
            return headers.erreur(
                409, "cette équipe est complète (%d membres au maximum)" % high)
        return headers.erreur(503, "la base ne répond pas")
    _entry, team, _low, _high, refused = _forming(sub, corps.assignment_id)
    vue = _mon_equipe(sub, entry, team) if team else None
    if vue is None:
        return headers.erreur(503, "la base ne répond pas")
    return {"team": vue}


@router.post("/team/leave")
def leave(sub: Sub, corps: TeamLeaveIn, request: Request):
    """Quitter, TANT QUE L'ÉQUIPE N'EST PAS CONFIRMÉE.

    Après, non : le document est déjà le travail de tous, et partir le
    laisserait à trois personnes qui n'ont pas choisi ça. Reste « Supprimer
    mes données », qui coûte l'XP et les messages -- en faire le seul moyen de
    partir est le prix du sérieux de la décision.
    """
    entry, team, _low, _high, refused = _forming(sub, corps.assignment_id)
    if refused is not None:
        return refused
    if team is None:
        return headers.erreur(404, "tu n'es dans aucune équipe pour ce devoir")
    freiner_ecriture(request)
    if not state.team_leave(sub, entry["id"]):
        return headers.erreur(
            409, "ton équipe est déjà confirmée : on n'en sort plus")
    return {"ok": True, "team": None}


@router.put("/team/settings")
def settings(sub: Sub, corps: TeamFormIn, request: Request):
    """Le nom et le groupe, tant que l'équipe n'est pas confirmée.

    N'IMPORTE QUEL MEMBRE, ET PAS DE CHEF. Tout le monde devra reconfirmer
    ensuite -- changer quelque chose ne fait que redemander l'accord de tous,
    et c'est ce qui remplace une hiérarchie qu'il faudrait attribuer.
    """
    entry, team, _low, _high, refused = _forming(sub, corps.assignment_id)
    if refused is not None:
        return refused
    if team is None:
        return headers.erreur(404, "tu n'es dans aucune équipe pour ce devoir")
    label, message = team_service.team_label(corps.label)
    if message:
        return headers.erreur(400, message)
    group, message = forum_groupe(corps.group_number)
    if message:
        return headers.erreur(400, message)
    freiner_ecriture(request)
    if not state.team_settings(sub, entry["id"], label, group):
        return headers.erreur(
            409, "ton équipe est déjà confirmée : son nom et son groupe sont "
                 "figés")
    _entry, team, _low, _high, refused = _forming(sub, corps.assignment_id)
    vue = _mon_equipe(sub, entry, team) if team else None
    if vue is None:
        return headers.erreur(503, "la base ne répond pas")
    return {"team": vue}


@router.post("/team/lock")
def lock(sub: Sub, corps: TeamLockIn, request: Request):
    """Confirmer la composition -- ET SCELLER SI C'ÉTAIT LA DERNIÈRE.

    LES DEUX DANS UNE SEULE INSTRUCTION SQL (voir `state.team_lock`) : deux
    derniers membres qui confirment au même instant liraient tous les deux
    « il en reste un » s'il fallait relire après avoir écrit.

    LE SCELLEMENT PEUT NE PAS SE PRODUIRE, et ce n'est pas une erreur : il
    manque un coéquipier, le groupe n'est pas choisi, quelqu'un n'a pas encore
    confirmé. La réponse porte `missing`, qui le dit -- un bouton qui ne fait
    rien sans expliquer est une équipe qui écrit à son enseignant.
    """
    entry, team, low, high, refused = _forming(sub, corps.assignment_id)
    if refused is not None:
        return refused
    if team is None:
        return headers.erreur(404, "tu n'es dans aucune équipe pour ce devoir")
    if team.get("sealed"):
        return headers.erreur(
            409, "ton équipe est déjà confirmée : on ne revient pas dessus")
    freiner_ecriture(request)
    if not state.team_lock(sub, entry["id"], corps.locked, low, high):
        return headers.erreur(503, "la base ne répond pas")
    _entry, team, _low, _high, refused = _forming(sub, corps.assignment_id)
    vue = _mon_equipe(sub, entry, team) if team else None
    if vue is None:
        return headers.erreur(503, "la base ne répond pas")
    return {"team": vue}


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
        vue = _mon_equipe(sub, entry, row)
        if vue is None:
            return headers.erreur(503, "la base ne répond pas")
        vue.update({
            "assignment_id": entry["id"],
            "assignment_title": entry.get("title", ""),
            "access": entry.get("access", "archived"),
            "available_from": (entry.get("release") or {}).get("available_from"),
            "deadline": entry.get("deadline"),
            "team": dict(entry.get("team") or {}),
        })
        out.append(vue)
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

CLOSE_UNAUTHORIZED = 4401
CLOSE_FORBIDDEN = 4403
CLOSE_BUSY = 4429
CLOSE_BAD = 4400

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
