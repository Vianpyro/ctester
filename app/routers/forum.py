import asyncio
import hmac
import json
import re
import secrets
import uuid

import config
import deps
import headers
import policy
import security
import state
from deps import SubForum, SubModerator, throttle_forum
from fastapi import APIRouter, Query, Request, WebSocket
from schemas import (DiscordBridgeIn, ForumTargetIn, ForumMessageIn, ForumModerationIn,
                     ForumProfileIn, ForumReportIn, ForumVoteIn)
from services.catalog import find_exercise
from services import discord
from services import forum as forum_service
from services import forum_live
from services import leaderboard
from starlette.concurrency import run_in_threadpool

MSG_RE = re.compile(r"\A[0-9a-f]{32}\Z")

router = APIRouter(tags=["forum"])


def _thread_entry(raw):
    key = str(raw or "")
    if not forum_service.is_chat(key):
        return find_exercise(key)
    if key == forum_service.CHAT_GENERAL:
        return {"id": key, "label": "Questions générales", "chat": True}
    entry = find_exercise(key[len(forum_service.CHAT_PREFIX):])
    if entry is None:
        return None
    return {"id": key, "label": entry.get("label") or key, "chat": True}


def _ensure_alias(sub):
    profile = state.forum_profile(sub)
    if not profile or profile.get("alias"):
        return
    taken = state.forum_taken_aliases()
    if taken is None:
        return
    alias = leaderboard.draw_alias(taken, secrets.randbelow(1 << 32))
    if not alias:
        return
    state.forum_write_profile(
        uuid.uuid4().hex, sub, profile.get("display_name"),
        profile.get("group_number"), bool(profile.get("display_name_public")),
        bool(profile.get("group_number_public")), alias=alias,
        plate_frame=profile.get("plate_frame"),
        badges_public=profile.get("badges_public"),
        leaderboard_opt_in=profile.get("leaderboard_opt_in"))


def _to_discord(entry, sub, text):
    if not discord.enabled() or not forum_service.is_chat(entry["id"]):
        return
    profiles = state.forum_profiles([sub]) or {}
    author, _group, _reportable = forum_service.forum_identity(
        profiles.get(sub), None, sub, False)
    discord.announce(entry["id"], sub, author, text,
                     entry.get("label", ""))


def _message_id(raw):
    value = str(raw or "")
    return value if MSG_RE.match(value) else None


@router.get("/forum")
def get_thread(sub: SubForum, ex: str = Query("")):
    entry = _thread_entry(ex)
    if entry is None:
        return headers.error(400, "TP inconnu")
    messages = state.forum_thread(entry["id"], config.FORUM_MAX_THREAD, sub)
    if messages is None:
        return headers.error(503, "la base ne répond pas")
    moderator = security.is_moderator(sub)
    profiles = state.forum_profiles(
        [m["account"] for m in messages] + [sub]) or {}
    views = forum_service.forum_view(messages, sub, moderator, profiles)
    return {
        "exercise_id": entry["id"],
        "chat": bool(entry.get("chat")),
        "moderator": moderator,
        "max": config.FORUM_MAX_CHARS,
        "messages": views,
        "state": forum_service.thread_state(views),
        "steps": [{"id": k, "title": v} for k, v in forum_service.STEPS.items()],
        "blocked_kinds": [{"id": k, "title": v}
                          for k, v in forum_service.BLOCKED_KINDS.items()],
    }


@router.post("/forum")
def post_message(sub: SubForum, body: ForumMessageIn):
    entry = _thread_entry(body.exercise_id)
    if entry is None:
        return headers.error(400, "TP inconnu")
    text, message = forum_service.forum_text(body.text)
    if message:
        return headers.error(400, message)

    reply_to = None
    if body.reply_to:
        reply_to = _message_id(body.reply_to)
        if reply_to is None:
            return headers.error(400, "identifiant invalide")
        if body.visibility:
            return headers.error(
                400, "une réponse hérite de la visibilité de sa question")

    throttle_forum(sub)
    _ensure_alias(sub)

    if reply_to is not None:
        written = state.forum_reply(uuid.uuid4().hex, entry["id"], sub,
                                    text, reply_to)
        if written is None:
            return headers.error(503, "la base ne répond pas")
        if not written:
            return headers.error(404, "message introuvable")
        forum_live.notify(entry["id"])
        _to_discord(entry, sub, text)
        return {"ok": True}

    step, message = forum_service.forum_step(body.step)
    if message:
        return headers.error(400, message)
    blocked_kind, message = forum_service.forum_blocked_kind(body.blocked_kind)
    if message:
        return headers.error(400, message)
    visibility, message = forum_service.forum_visibility(
        body.visibility, step is not None, entry["id"])
    if message:
        return headers.error(400, message)
    if not state.forum_post(uuid.uuid4().hex, entry["id"], sub, text,
                            step, blocked_kind, visibility):
        return headers.error(503, "la base ne répond pas")
    forum_live.notify(entry["id"])
    _to_discord(entry, sub, text)
    return {"ok": True}


_DISCORD_ID_RE = re.compile(r"\A[0-9]{1,24}\Z")


@router.post("/forum/bridge")
def discord_bridge(body: DiscordBridgeIn, request: Request):
    if not config.DISCORD_BRIDGE_KEY:
        return headers.error(404, "inconnu")
    presented = request.headers.get("authorization", "")
    expected = "Bearer " + config.DISCORD_BRIDGE_KEY
    if not hmac.compare_digest(presented, expected):
        return headers.error(401, "clé du pont invalide")

    entry = _thread_entry(body.exercise_id)
    if entry is None:
        return headers.error(400, "TP inconnu")
    if not forum_service.is_chat(entry["id"]):
        return headers.error(400, "le pont n'écrit que dans le chat public")

    if not _DISCORD_ID_RE.match(str(body.discord_id or "")):
        return headers.error(400, "identifiant Discord invalide")
    text, message = forum_service.forum_text(body.text)
    if message:
        return headers.error(400, message)
    display_name, message = forum_service.forum_display_name(body.display_name)
    if message:
        return headers.error(400, message)

    # Each Discord user is a service account; nothing links it to a student account.
    account = config.DISCORD_ACCOUNT_PREFIX + str(body.discord_id)
    throttle_forum(account)

    profile = state.forum_profile(account)
    if profile is None:
        return headers.error(503, "la base ne répond pas")
    if (display_name or None) != profile.get("display_name"):
        state.forum_write_profile(
            uuid.uuid4().hex, account, display_name, profile.get("group_number"),
            True, bool(profile.get("group_number_public")),
            alias=profile.get("alias"), plate_frame=profile.get("plate_frame"),
            badges_public=profile.get("badges_public"),
            leaderboard_opt_in=profile.get("leaderboard_opt_in"))

    if not state.forum_post(uuid.uuid4().hex, entry["id"], account, text,
                            None, None, "thread"):
        return headers.error(503, "la base ne répond pas")
    forum_live.notify(entry["id"])
    return {"ok": True}


@router.get("/forum/activity")
def get_activity(sub: SubForum):
    """The last message per thread, so the page can light an unread dot without
    opening every channel."""
    threads = state.forum_activity(
        sub, security.is_moderator(sub), config.FORUM_ACTIVITY_DAYS)
    if threads is None:
        return headers.error(503, "la base ne répond pas")
    return {"threads": threads}


@router.get("/forum/search")
def search(sub: SubForum, q: str = Query("")):
    results = state.forum_search(q, sub, config.FORUM_SEARCH_MAX)
    if results is None:
        return headers.error(503, "la base ne répond pas")
    return {"results": results}


@router.get("/forum/message")
def permalink(sub: SubForum, id: str = Query("")):
    message_id = _message_id(id)
    if message_id is None:
        return headers.error(400, "identifiant invalide")
    thread, messages = state.forum_conversation(message_id, sub)
    if messages is None:
        return headers.error(503, "la base ne répond pas")
    if not messages:
        return headers.error(404, "message introuvable")
    moderator = security.is_moderator(sub)
    profiles = state.forum_profiles(
        [m["account"] for m in messages] + [sub]) or {}
    views = forum_service.forum_view(messages, sub, moderator, profiles)
    if not views:
        return headers.error(404, "message introuvable")
    return {"exercise_id": thread, "chat": forum_service.is_chat(thread),
            "moderator": moderator, "messages": views}


@router.post("/forum/visibility")
def open_to_group(sub: SubForum, body: ForumTargetIn):
    message_id = _message_id(body.id)
    if message_id is None:
        return headers.error(400, "identifiant invalide")
    throttle_forum(sub)
    opened = state.forum_open_to_group(message_id, sub)
    if opened is None:
        return headers.error(503, "la base ne répond pas")
    if not opened:
        return headers.error(404, "message introuvable")
    return {"ok": True}


@router.post("/forum/helpful")
def vote(sub: SubForum, body: ForumVoteIn):
    message_id = _message_id(body.id)
    if message_id is None:
        return headers.error(400, "identifiant invalide")
    throttle_forum(sub)
    if int(body.value) == 0:
        marked = state.forum_unvote(message_id, sub)
    else:
        marked = state.forum_vote(message_id, sub, body.value)
    if marked is None:
        return headers.error(503, "la base ne répond pas")
    if not marked:
        return headers.error(404, "message introuvable")
    return {"ok": True}


@router.delete("/forum")
def delete_message(sub: SubForum, id: str = Query("")):
    message_id = _message_id(id)
    if message_id is None:
        return headers.error(400, "identifiant invalide")
    thread = state.forum_thread_of(message_id)
    cleared = state.forum_delete(message_id, sub)
    if cleared is None:
        return headers.error(503, "la base ne répond pas")
    if not cleared:
        return headers.error(404, "message introuvable")
    forum_live.notify(thread)
    return {"ok": True}


@router.post("/forum/signalement")
def report(sub: SubForum, body: ForumReportIn):
    message_id = _message_id(body.id)
    if message_id is None:
        return headers.error(400, "identifiant invalide")
    throttle_forum(sub)
    if body.kind == "name":
        if state.forum_report_name(message_id, sub) is None:
            return headers.error(503, "la base ne répond pas")
        return {"ok": True}
    if state.forum_report(message_id, sub) is None:
        return headers.error(503, "la base ne répond pas")
    return {"ok": True}


@router.get("/forum/moderation")
def moderation_queue(sub: SubModerator):
    reported = state.forum_reports(config.FORUM_MAX_THREAD)
    names = state.forum_reported_names(config.FORUM_MAX_THREAD)
    if reported is None or names is None:
        return headers.error(503, "la base ne répond pas")
    return {"reports": reported, "reported_names": [
        {"id": n["id"], "display_name": n["display_name"], "group_number": n["group_number"],
         "created_at": n["created_at"], "report_count": n["report_count"]}
        for n in names]}


@router.post("/forum/moderation")
def moderate(sub: SubModerator, body: ForumModerationIn):
    message_id = _message_id(body.id)
    if message_id is None:
        return headers.error(400, "identifiant invalide")
    if body.action == "clear-name":
        return _clear_name(message_id)
    if body.action not in ("hide", "restore", "retain", "unretain"):
        return headers.error(400, "action inconnue")
    thread = state.forum_thread_of(message_id)
    done = state.forum_moderate(uuid.uuid4().hex, message_id, sub, body.action)
    if done is None:
        return headers.error(503, "la base ne répond pas")
    if not done:
        return headers.error(404, "message introuvable")
    forum_live.notify(thread)
    return {"ok": True}


HELP_WINDOW_HOURS = 8


@router.get("/forum/help")
def who_needs_help(sub: SubModerator):
    rows = state.forum_help_rows(config.FORUM_MAX_THREAD, HELP_WINDOW_HOURS)
    if rows is None:
        return headers.error(503, "la base ne répond pas")
    return {"rows": rows, "hours": HELP_WINDOW_HOURS,
            "steps": [{"id": k, "title": v} for k, v in forum_service.STEPS.items()],
            "blocked_kinds": [{"id": k, "title": v}
                              for k, v in forum_service.BLOCKED_KINDS.items()]}


@router.get("/forum/top")
def top(sub: SubModerator):
    rows = state.forum_top(HELP_WINDOW_HOURS, config.FORUM_MAX_THREAD)
    if rows is None:
        return headers.error(503, "la base ne répond pas")
    return {"rows": rows, "hours": HELP_WINDOW_HOURS}


def _clear_name(message_id):
    author = state.forum_author(message_id)
    if not author:
        return headers.error(404, "message introuvable")
    profile = state.forum_profile(author)
    if profile is None:
        return headers.error(503, "la base ne répond pas")
    if not state.forum_write_profile(
            uuid.uuid4().hex, author, None, profile.get("group_number"), False,
            bool(profile.get("group_number_public")), set_by_moderator=True,
            alias=profile.get("alias"), plate_frame=profile.get("plate_frame"),
            badges_public=profile.get("badges_public"),
            leaderboard_opt_in=profile.get("leaderboard_opt_in")):
        return headers.error(503, "la base ne répond pas")
    return {"ok": True}


@router.get("/forum/profil")
def get_profile(sub: SubForum, request: Request):
    profile = state.forum_profile(sub)
    if profile is None:
        return headers.error(503, "la base ne répond pas")
    facts = state.read_progress(sub)
    rank = policy.level(facts["xp"])["rank"] if facts else 1
    return dict(profile, max_display_name=config.FORUM_PSEUDO_MAX,
                group_numbers=list(config.FORUM_GROUPS),
                frames=policy.unlocked_frames(rank),
                suggestion=("" if profile.get("display_name")
                            else security.current_name(request.headers)))


@router.post("/forum/profil")
def put_profile(sub: SubForum, body: ForumProfileIn):
    display_name, message = forum_service.forum_display_name(body.display_name)
    if message:
        return headers.error(400, message)
    group, message = forum_service.forum_group(body.group_number)
    if message:
        return headers.error(400, message)
    previous = state.forum_profile(sub)
    if previous is None:
        return headers.error(503, "la base ne répond pas")
    facts = state.read_progress(sub)
    frame, message = forum_service.forum_frame(
        body.plate_frame,
        policy.unlocked_frames(policy.level(facts["xp"])["rank"] if facts else 1))
    if message:
        return headers.error(400, message)
    alias = previous.get("alias")
    if body.leaderboard_opt_in and not alias:
        taken = state.forum_taken_aliases()
        if taken is None:
            return headers.error(503, "la base ne répond pas")
        alias = leaderboard.draw_alias(taken, secrets.randbelow(1 << 32))
    throttle_forum(sub)
    if not state.forum_write_profile(
            uuid.uuid4().hex, sub, display_name, group,
            body.display_name_public and display_name is not None,
            body.group_number_public and group is not None,
            alias=alias, plate_frame=frame,
            badges_public=body.badges_public,
            leaderboard_opt_in=body.leaderboard_opt_in):
        return headers.error(503, "la base ne répond pas")
    return {"ok": True}


@router.websocket("/forum/live")
async def live(socket: WebSocket):
    """A doorbell: clients re-fetch GET /forum, so visibility rules stay in one place."""
    origin = socket.headers.get("origin", "").strip().rstrip("/")
    if origin and origin not in config.ORIGINS:
        await socket.close(code=deps.CLOSE_FORBIDDEN)
        return
    await socket.accept()
    try:
        hello = await asyncio.wait_for(socket.receive_text(), timeout=10)
    except Exception:
        await socket.close(code=deps.CLOSE_BAD)
        return
    if len(hello) > config.FORUM_LIVE_FRAME:
        await socket.close(code=deps.CLOSE_BAD)
        return
    try:
        opening = json.loads(hello)
    except ValueError:
        opening = None
    if not isinstance(opening, dict) or opening.get("t") != "hello":
        await socket.close(code=deps.CLOSE_BAD)
        return
    token, thread = opening.get("token"), opening.get("thread")
    if not isinstance(token, str) or not token or not isinstance(thread, str):
        await socket.close(code=deps.CLOSE_BAD)
        return

    if not forum_service.forum_enabled():
        await socket.close(code=deps.CLOSE_UNAVAILABLE)
        return

    sub = await run_in_threadpool(security.current_user,
                                  {"Authorization": "Bearer " + token})
    if not sub:
        await socket.close(code=deps.CLOSE_UNAUTHORIZED)
        return

    entry = await run_in_threadpool(_thread_entry, thread)
    if entry is None:
        await socket.close(code=deps.CLOSE_BAD)
        return
    key = entry["id"]
    if forum_live.full(key):
        await socket.close(code=deps.CLOSE_BUSY)
        return

    connection = forum_live.Connection(socket, key)
    forum_live.join(connection)
    try:
        await connection.send({"t": "ready", "thread": key})
        while True:
            incoming = await socket.receive_text()
            if len(incoming) > config.FORUM_LIVE_FRAME:
                await socket.close(code=deps.CLOSE_BAD)
                return
    except Exception:
        pass
    finally:
        forum_live.leave(connection)
