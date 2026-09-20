import json
import uuid

import config
import deps
import headers
import security
import state
from deps import Sub, throttle_write
from fastapi import APIRouter, Query, Request, WebSocket
from schemas import (TeamDocumentIn, TeamHandinIn, TeamJoinIn, TeamLeaveIn,
                     TeamRestoreIn)
from services import collab
from services import teams as team_service
from services.catalog import find_exercise, validate_files
from starlette.concurrency import run_in_threadpool
from starlette.responses import Response

router = APIRouter(tags=["team"])

MAX_FRAME = config.TEAM_LIVE_MAX_FRAME


def _gate(sub, assignment_id, exercise_id=None):
    """The team always comes from the token's account, never from the request.

    Being in the team does not prove the exercise belongs to the assignment,
    hence the second check.
    """
    assignment, team, refusal = team_service.workspace(state, sub, assignment_id)
    if refusal:
        return None, None, headers.error(*refusal)
    if exercise_id is not None and not team_service.exercise_in(assignment, exercise_id):
        return None, None, headers.error(404, "exercice inconnu pour ce devoir")
    return assignment, team, None


@router.get("/team/context")
def context(sub: Sub, assignment: str = Query("", alias="assignment")):
    entry, team, refused = _gate(sub, assignment)
    if refused is not None:
        return refused
    roster = state.team_roster(entry["id"], team["team_id"])
    if roster is None:
        return headers.error(503, "la base ne répond pas")
    profiles = state.forum_profiles(roster) or {}
    submission = state.read_team_submission(entry["id"], team["team_id"])
    if submission is None:
        return headers.error(503, "la base ne répond pas")
    return {
        "assignment": team_service.assignment_view(entry),
        "team": {"id": team["team_id"],
                 "label": team["label"] or team_service.TEAM_NAME % team["number"],
                 "number": team["number"], "group_number": team["group_number"],
                 "members": team_service.members_view(roster, sub, profiles)},
        "submission": submission,
    }


def _team_choice(sub, assignment_id):
    entry = team_service.published_assignment(assignment_id)
    if entry is None:
        return None, None, headers.error(404, "devoir inconnu")
    if not team_service.is_team_assignment(entry):
        return None, None, headers.error(
            400, "ce devoir n'est pas un travail d'équipe")
    if not team_service.joinable(entry):
        return None, None, headers.error(
            409, "les équipes sont figées : le devoir est ouvert")
    profile = state.forum_profile(sub) or {}
    group = profile.get("group_number")
    if group is None:
        return None, None, headers.error(
            409, "choisis d'abord ton groupe dans « Mon identité » : les "
                 "équipes sont numérotées par groupe")
    return entry, int(group), None


@router.get("/team/available")
def available(sub: Sub, assignment: str = Query("")):
    entry, group, refused = _team_choice(sub, assignment)
    if refused is not None:
        return refused
    existing = state.team_counts(entry["id"], group)
    if existing is None:
        return headers.error(503, "la base ne répond pas")
    own_team = state.team_of(sub, entry["id"])
    return {"assignment_id": entry["id"], "group_number": group,
            "mine": own_team["number"] if own_team else None,
            "teams": team_service.available_teams(entry, group, existing)}


@router.post("/team/join")
def join(sub: Sub, body: TeamJoinIn, request: Request):
    entry, group, refused = _team_choice(sub, body.assignment_id)
    if refused is not None:
        return refused
    if state.team_of(sub, entry["id"]) is not None:
        return headers.error(
            409, "tu es déjà dans une équipe : quitte-la d'abord")
    _low, high, count = team_service.team_size(entry)
    if not 1 <= body.number <= count:
        return headers.error(
            404, "cette équipe n'existe pas (il y en a %d)" % count)
    team_id = team_service.team_handle(group, body.number)
    throttle_write(request)
    if not state.team_join(sub, entry["id"], team_id, group, body.number,
                           team_service.TEAM_NAME % body.number, high):
        return headers.error(
            409, "cette équipe est complète (%d places)" % high)
    return available(sub, entry["id"])


@router.post("/team/leave")
def leave(sub: Sub, body: TeamLeaveIn, request: Request):
    entry, _group, refused = _team_choice(sub, body.assignment_id)
    if refused is not None:
        return refused
    if state.team_of(sub, entry["id"]) is None:
        return headers.error(404, "tu n'es dans aucune équipe pour ce devoir")
    throttle_write(request)
    if not state.team_leave(sub, entry["id"]):
        return headers.error(503, "la base ne répond pas")
    return available(sub, entry["id"])


@router.get("/team/mine")
def mine(sub: Sub):
    rows = state.team_memberships(sub)
    if rows is None:
        return headers.error(503, "la base ne répond pas")
    out = []
    for row in rows:
        entry = team_service.published_assignment(row["assignment_id"])
        if entry is None:
            continue
        roster = state.team_roster(row["assignment_id"], row["team_id"])
        if roster is None:
            return headers.error(503, "la base ne répond pas")
        profiles = state.forum_profiles(roster) or {}
        out.append({
            "assignment_id": entry["id"],
            "assignment_title": entry.get("title", ""),
            "access": entry.get("access", "archived"),
            "available_from": (entry.get("release") or {}).get("available_from"),
            "deadline": entry.get("deadline"),
            "joinable": team_service.joinable(entry),
            "number": row["number"],
            "label": row["label"] or team_service.TEAM_NAME % row["number"],
            "group_number": row["group_number"],
            "members": team_service.members_view(roster, sub, profiles),
        })
    return {"teams": out}


@router.get("/team/document")
def read_document(sub: Sub, assignment: str = Query(""), ex: str = Query("")):
    entry, team, refused = _gate(sub, assignment, ex)
    if refused is not None:
        return refused
    sources = state.read_team_document(team["team_id"], ex)
    if sources is None:
        return headers.error(503, "la base ne répond pas")
    catalog_entry = find_exercise(ex)
    if catalog_entry is not None and sources:
        checked, message, _ = validate_files(catalog_entry, sources)
        sources = checked if message is None else {}
    return {"exercise_id": ex, "sources": sources}


@router.put("/team/document")
def write_document(sub: Sub, body: TeamDocumentIn, request: Request):
    _, team, refused = _gate(sub, body.assignment_id, body.exercise_id)
    if refused is not None:
        return refused
    catalog_entry = find_exercise(body.exercise_id)
    if catalog_entry is None:
        return headers.error(404, "exercice inconnu pour ce devoir")
    files, message, code = validate_files(catalog_entry, body.files)
    if message:
        return headers.error(code, message)
    throttle_write(request)
    if not state.write_team_document(team["team_id"], body.exercise_id, sub,
                                     files, uuid.uuid4().hex,
                                     config.TEAM_REVISION_WINDOW):
        return headers.error(503, "la base ne répond pas")
    return {"ok": True}


@router.get("/team/revisions")
def revisions(sub: Sub, assignment: str = Query(""), ex: str = Query("")):
    entry, team, refused = _gate(sub, assignment, ex)
    if refused is not None:
        return refused
    roster = state.team_roster(entry["id"], team["team_id"])
    rows = state.read_team_revisions(team["team_id"], ex,
                                     config.TEAM_REVISIONS_MAX)
    if rows is None or roster is None:
        return headers.error(503, "la base ne répond pas")
    return {"exercise_id": ex,
            "revisions": team_service.revisions_view(rows, roster)}


@router.get("/team/revision")
def revision(sub: Sub, assignment: str = Query(""), ex: str = Query(""),
             id: str = Query("")):
    entry, team, refused = _gate(sub, assignment, ex)
    if refused is not None:
        return refused
    sources = state.read_team_revision(team["team_id"], id)
    if sources is None:
        return headers.error(503, "la base ne répond pas")
    if not sources:
        return headers.error(404, "révision inconnue")
    return {"revision_id": id, "sources": sources}


@router.post("/team/restore")
def restore(sub: Sub, body: TeamRestoreIn, request: Request):
    _, team, refused = _gate(sub, body.assignment_id, body.exercise_id)
    if refused is not None:
        return refused
    catalog_entry = find_exercise(body.exercise_id)
    if catalog_entry is None:
        return headers.error(404, "exercice inconnu pour ce devoir")
    sources = state.read_team_revision(team["team_id"], body.revision_id)
    if sources is None:
        return headers.error(503, "la base ne répond pas")
    if not sources:
        return headers.error(404, "révision inconnue")
    files, message, code = validate_files(catalog_entry, sources)
    if message:
        return headers.error(code, message)
    throttle_write(request)
    if not state.write_team_document(team["team_id"], body.exercise_id, sub,
                                     files, uuid.uuid4().hex, 0):
        return headers.error(503, "la base ne répond pas")
    return {"ok": True, "sources": files}


def _handin(sub, assignment_id):
    entry, team, refused = _gate(sub, assignment_id)
    if refused is not None:
        return None, None, None, None, refused
    if not (entry.get("handin") or {}).get("files"):
        return None, None, None, None, headers.error(
            400, "ce devoir ne déclare pas de remise")
    files, missing = team_service.handin_files(state, entry, team["team_id"],
                                               find_exercise)
    if files is None:
        return None, None, None, None, headers.error(503, "la base ne répond pas")
    return entry, team, files, missing, None


@router.get("/team/handin.zip")
def handin_zip(sub: Sub, assignment: str = Query("")):
    entry, team, files, missing, refused = _handin(sub, assignment)
    if refused is not None:
        return refused
    if not files:
        return headers.error(400, "il n'y a encore rien à remettre")
    body = team_service.build_zip(files)
    return Response(body, media_type="application/zip", headers={
        "Content-Disposition": 'attachment; filename="%s"'
                               % team_service.archive_name(entry, team),
        "Cache-Control": "no-store",
    })


@router.post("/team/handin")
def handin(sub: Sub, body: TeamHandinIn, request: Request):
    entry, team, files, missing, refused = _handin(sub, body.assignment_id)
    if refused is not None:
        return refused
    if team_service.deadline_passed(entry):
        return headers.error(403, "la date de remise est passée")
    if missing:
        return headers.error(
            400, "remise incomplète : " + ", ".join(m["name"] for m in missing))
    throttle_write(request)
    if not state.write_team_submission(entry["id"], team["team_id"], sub, files):
        return headers.error(503, "la base ne répond pas")
    submission = state.read_team_submission(entry["id"], team["team_id"])
    return {"ok": True, "submission": submission or {},
            "files": sorted(files)}


RELAYED = ("sync", "update", "cursor")


@router.websocket("/team/live")
async def live(socket: WebSocket):
    opening = await deps.hello(socket, MAX_FRAME)
    if opening is None:
        return
    token = opening.get("token")
    assignment_id = opening.get("assignment")
    exercise_id = opening.get("exercise")
    if not all(isinstance(v, str) and v for v in (token, assignment_id, exercise_id)):
        await socket.close(code=deps.CLOSE_BAD)
        return

    sub = await run_in_threadpool(security.current_user,
                                  {"Authorization": "Bearer " + token})
    if not sub:
        await socket.close(code=deps.CLOSE_UNAUTHORIZED)
        return

    def resolve():
        assignment, team, refusal = team_service.workspace(state, sub, assignment_id)
        if refusal or not team_service.exercise_in(assignment, exercise_id):
            return None, None, None
        return assignment, team, state.team_roster(assignment["id"], team["team_id"])

    assignment, team, roster = await run_in_threadpool(resolve)
    if team is None or roster is None:
        await socket.close(code=deps.CLOSE_FORBIDDEN)
        return

    key = collab.room_key(team["team_id"], exercise_id)
    if collab.full(key):
        await socket.close(code=deps.CLOSE_BUSY)
        return
    connection = collab.Connection(socket, key,
                                   team_service.member_handle(roster, sub), sub)
    epoch, peers = collab.join(connection)
    try:
        await connection.send({"t": "ready", "epoch": epoch, "peers": peers,
                               "me": connection.handle,
                               "exercise": exercise_id})
        await collab.announce(key)
        while True:
            raw = await socket.receive_text()
            if len(raw) > MAX_FRAME:
                await socket.close(code=deps.CLOSE_BAD)
                return
            try:
                frame = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(frame, dict) or frame.get("t") not in RELAYED:
                continue
            # Stamped by the server, so nobody can move a teammate's cursor.
            frame["from"] = connection.handle
            frame.pop("token", None)
            await collab.broadcast(connection, frame)
    except Exception:
        pass
    finally:
        collab.leave(connection)
        await collab.announce(key)


@router.get("/team/roster")
def roster_view(sub: Sub, assignment: str = Query("")):
    if not security.is_moderator(sub):
        return headers.error(403, "réservé à l'enseignant")
    entry = team_service.find_assignment(assignment)
    if entry is None:
        return headers.error(404, "devoir inconnu")
    rows = state.read_teams(entry["id"])
    if rows is None:
        return headers.error(503, "la base ne répond pas")
    return {"assignment_id": entry["id"], "teams": rows}
