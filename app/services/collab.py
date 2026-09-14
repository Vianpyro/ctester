"""Relays Yjs frames between members of a room without interpreting them.

Rooms live in process memory, which is one reason uvicorn runs a single worker.
"""
import json
import uuid

import config

_rooms = {}


class Connection:
    def __init__(self, socket, key, handle, account):
        self.socket = socket
        self.key = key
        self.handle = handle
        self.account = account

    async def send(self, payload):
        try:
            await self.socket.send_text(json.dumps(payload))
        except Exception:
            pass


def room_key(team_id, exercise_id):
    return team_id + "\x00" + exercise_id


def join(connection):
    room = _rooms.get(connection.key)
    # A rebuilt room gets a new epoch, so returning clients drop their stale
    # document instead of merging it. The first peer seeds from the database.
    if room is None or len(room["members"]) == 0:
        room = {"epoch": uuid.uuid4().hex, "members": []}
        _rooms[connection.key] = room
    peers = len(room["members"])
    room["members"].append(connection)
    return room["epoch"], peers


def full(key):
    room = _rooms.get(key)
    return bool(room) and len(room["members"]) >= config.TEAM_LIVE_MAX


def leave(connection):
    room = _rooms.get(connection.key)
    if room is None:
        return
    room["members"] = [m for m in room["members"] if m is not connection]
    if not room["members"]:
        _rooms.pop(connection.key, None)


def members(key):
    room = _rooms.get(key)
    seen, out = set(), []
    for member in (room or {}).get("members", ()):
        if member.handle not in seen:
            seen.add(member.handle)
            out.append(member.handle)
    return out


async def broadcast(connection, payload):
    room = _rooms.get(connection.key)
    for member in list((room or {}).get("members", ())):
        if member is not connection:
            await member.send(payload)


async def announce(key):
    room = _rooms.get(key)
    payload = {"t": "presence", "online": members(key)}
    for member in list((room or {}).get("members", ())):
        await member.send(payload)


def reset():
    _rooms.clear()
